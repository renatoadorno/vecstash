use anyhow::{Context, Result, bail};
use regex::Regex;
use scraper::{Html, Selector};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;
use std::sync::OnceLock;
use unicode_normalization::UnicodeNormalization;

#[derive(Debug, Clone, PartialEq)]
pub struct ExtractedDocument {
    pub document_id: String,
    pub source_path: String,
    pub source_kind: String,
    pub content_hash: String,
    pub byte_size: u64,
    pub char_count: usize,
    pub line_count: usize,
    pub text: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceKind {
    Txt,
    Md,
    Html,
}

impl SourceKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            SourceKind::Txt => "txt",
            SourceKind::Md => "md",
            SourceKind::Html => "html",
        }
    }

    fn from_path(path: &Path) -> Result<Self> {
        let Some(extension) = path.extension() else {
            bail!(
                "Unsupported file type for {}. Supported suffixes: .htm, .html, .markdown, .md, .txt",
                path.display()
            );
        };
        match extension.to_string_lossy().to_lowercase().as_str() {
            "txt" => Ok(SourceKind::Txt),
            "md" | "markdown" => Ok(SourceKind::Md),
            "html" | "htm" => Ok(SourceKind::Html),
            other => bail!(
                "Unsupported file type '.{other}' for {}. Supported suffixes: .htm, .html, .markdown, .md, .txt",
                path.display()
            ),
        }
    }
}

fn separator_line() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[-|:=][-|:=\s]+$").expect("valid regex"))
}

fn md_separator_line() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[ \t]*\|[\s:|-]+\|[ \t]*$").expect("valid regex"))
}

fn md_inline() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"`([^`]+)`").expect("valid regex"))
}

fn md_bold() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\*{1,3}([^*]+)\*{1,3}").expect("valid regex"))
}

fn md_link() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\[([^\]]+)\]\([^)]+\)").expect("valid regex"))
}

fn strip_md_inline(text: &str) -> String {
    let text = md_inline().replace_all(text, "$1");
    let text = md_bold().replace_all(&text, "$1");
    let text = md_link().replace_all(&text, "$1");
    text.into_owned()
}

fn parse_md_row(line: &str) -> Vec<String> {
    let trimmed = line.trim().trim_matches('|');
    let mut cells = Vec::new();
    for cell in trimmed.split('|') {
        cells.push(strip_md_inline(cell.trim()));
    }
    cells
}

fn is_md_table_line(line: &str) -> bool {
    let trimmed = line.trim();
    trimmed.starts_with('|') && trimmed.ends_with('|') && trimmed.len() > 1
}

pub fn linearize_md_tables(raw: &str) -> String {
    let lines: Vec<&str> = raw.split('\n').collect();
    let mut out: Vec<String> = Vec::new();
    let mut index = 0;

    while index < lines.len() {
        if !is_md_table_line(lines[index]) {
            out.push(lines[index].to_string());
            index += 1;
            continue;
        }

        let start = index;
        while index < lines.len() && is_md_table_line(lines[index]) {
            index += 1;
        }

        let mut block: Vec<&str> = Vec::new();
        for line in &lines[start..index] {
            if line.trim().is_empty() || md_separator_line().is_match(line) {
                continue;
            }
            block.push(line);
        }

        if block.len() < 2 {
            for line in &lines[start..index] {
                out.push(line.to_string());
            }
            continue;
        }

        let headers = parse_md_row(block[0]);
        let mut rendered: Vec<String> = Vec::new();
        for row in &block[1..] {
            let cells = parse_md_row(row);
            let mut pairs: Vec<String> = Vec::new();
            for (position, cell) in cells.iter().enumerate() {
                let key = match headers.get(position) {
                    Some(header) => header.clone(),
                    None => format!("col_{position}"),
                };
                pairs.push(format!("{key}: {cell}"));
            }
            rendered.push(pairs.join("\n"));
        }
        out.push(rendered.join("\n\n"));
    }

    out.join("\n")
}

fn linearize_table(table: scraper::ElementRef<'_>) -> String {
    let row_selector = Selector::parse("tr").expect("valid selector");
    let th_selector = Selector::parse("th").expect("valid selector");
    let td_selector = Selector::parse("td").expect("valid selector");

    let mut headers: Vec<String> = Vec::new();
    let mut data_rows: Vec<Vec<String>> = Vec::new();

    for row in table.select(&row_selector) {
        let mut header_cells: Vec<String> = Vec::new();
        for cell in row.select(&th_selector) {
            header_cells.push(cell.text().collect::<String>().trim().to_string());
        }
        if !header_cells.is_empty() {
            if headers.is_empty() {
                headers = header_cells;
            }
            continue;
        }

        let mut cells: Vec<String> = Vec::new();
        for cell in row.select(&td_selector) {
            cells.push(cell.text().collect::<String>().trim().to_string());
        }
        if !cells.is_empty() {
            data_rows.push(cells);
        }
    }

    if headers.is_empty() && !data_rows.is_empty() {
        headers = data_rows.remove(0);
    }

    let mut rendered: Vec<String> = Vec::new();
    for row in &data_rows {
        if headers.len() == 2 && row.len() >= 2 {
            rendered.push(format!("{}: {}", row[0], row[1]));
            continue;
        }
        let mut parts: Vec<String> = Vec::new();
        for (position, cell) in row.iter().enumerate() {
            match headers.get(position) {
                Some(header) => parts.push(format!("{header}: {cell}")),
                None => parts.push(cell.clone()),
            }
        }
        rendered.push(parts.join(", "));
    }
    rendered.join("\n")
}

fn has_table_ancestor(element: scraper::ElementRef<'_>) -> bool {
    let mut parent = element.parent();
    while let Some(node) = parent {
        if let Some(value) = node.value().as_element()
            && value.name() == "table"
        {
            return true;
        }
        parent = node.parent();
    }
    false
}

pub fn linearize_html_tables(html: &str) -> String {
    let document = Html::parse_document(html);
    let table_selector = Selector::parse("table").expect("valid selector");

    let mut out: Vec<String> = Vec::new();
    for table in document.select(&table_selector) {
        out.push(linearize_table(table));
    }
    out.join("\n\n")
}

fn extract_structured_html(html: &str) -> String {
    let document = Html::parse_document(html);
    let selector = Selector::parse("h1, h2, h3, p, li, table").expect("valid selector");

    let mut out: Vec<String> = Vec::new();
    for element in document.select(&selector) {
        let name = element.value().name();

        if name == "table" {
            let rendered = linearize_table(element);
            if !rendered.is_empty() {
                out.push(rendered);
            }
            continue;
        }

        if has_table_ancestor(element) {
            continue;
        }

        let text = element.text().collect::<String>();
        let text = text.trim();
        if text.is_empty() {
            continue;
        }
        let line = match name {
            "h1" => format!("# {text}"),
            "h2" => format!("## {text}"),
            "h3" => format!("### {text}"),
            "li" => format!("- {text}"),
            _ => text.to_string(),
        };
        out.push(line);
    }
    out.join("\n")
}

pub fn normalize_text(raw: &str) -> String {
    let normalized: String = raw.nfkc().collect();
    let normalized = normalized.replace("\r\n", "\n").replace('\r', "\n");

    let mut lines: Vec<String> = Vec::new();
    let mut previous_blank = false;
    for line in normalized.split('\n') {
        let mut compact = String::with_capacity(line.len());
        let mut in_space = false;
        for character in line.chars() {
            let is_space = character == ' '
                || character == '\t'
                || character == '\u{000b}'
                || character == '\u{000c}';
            if is_space {
                in_space = true;
                continue;
            }
            if in_space && !compact.is_empty() {
                compact.push(' ');
            }
            in_space = false;
            compact.push(character);
        }
        let compact = compact.trim();

        if !compact.is_empty() {
            if separator_line().is_match(compact) {
                continue;
            }
            lines.push(compact.to_string());
            previous_blank = false;
            continue;
        }
        if !previous_blank {
            lines.push(String::new());
            previous_blank = true;
        }
    }

    let joined = lines.join("\n");
    let joined = joined.trim();

    let mut collapsed = String::with_capacity(joined.len());
    let mut newline_run = 0;
    for character in joined.chars() {
        if character == '\n' {
            newline_run += 1;
            if newline_run > 2 {
                continue;
            }
        } else {
            newline_run = 0;
        }
        collapsed.push(character);
    }
    collapsed
}

fn render_markdown(raw: &str) -> String {
    let raw = linearize_md_tables(raw);
    let parser = pulldown_cmark::Parser::new(&raw);
    let mut html = String::new();
    pulldown_cmark::html::push_html(&mut html, parser);
    html
}

pub fn extract_file(path: &Path) -> Result<ExtractedDocument> {
    let path = path
        .canonicalize()
        .with_context(|| format!("File not found: {}", path.display()))?;
    if !path.is_file() {
        bail!("Path is not a file: {}", path.display());
    }

    let kind = SourceKind::from_path(&path)?;
    let contents = fs::read_to_string(&path)
        .with_context(|| format!("Cannot read {} as UTF-8", path.display()))?;

    let text = match kind {
        SourceKind::Txt => contents,
        SourceKind::Md => extract_structured_html(&render_markdown(&contents)),
        SourceKind::Html => extract_structured_html(&contents),
    };
    let text = normalize_text(&text);

    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    let content_hash = hex::encode(hasher.finalize());

    let mut hasher = Sha256::new();
    hasher.update(format!("{}:{content_hash}", path.display()).as_bytes());
    let document_id = hex::encode(hasher.finalize());

    let byte_size = fs::metadata(&path)?.len();
    let line_count = if text.is_empty() {
        0
    } else {
        text.matches('\n').count() + 1
    };

    Ok(ExtractedDocument {
        document_id,
        source_path: path.display().to_string(),
        source_kind: kind.as_str().to_string(),
        content_hash,
        byte_size,
        char_count: text.chars().count(),
        line_count,
        text,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_temp(name: &str, contents: &str) -> (tempfile::TempDir, std::path::PathBuf) {
        let dir = tempfile::tempdir().expect("tempdir");
        let path = dir.path().join(name);
        let mut file = fs::File::create(&path).expect("create");
        file.write_all(contents.as_bytes()).expect("write");
        (dir, path)
    }

    #[test]
    fn normalize_collapses_whitespace() {
        assert_eq!(normalize_text("a   \t  b"), "a b");
    }

    #[test]
    fn normalize_collapses_blank_lines() {
        assert_eq!(normalize_text("a\n\n\n\n\nb"), "a\n\nb");
    }

    #[test]
    fn normalize_drops_separator_lines() {
        assert_eq!(normalize_text("a\n------\nb"), "a\nb");
    }

    #[test]
    fn normalize_keeps_content_with_pipes() {
        assert_eq!(normalize_text("name | value"), "name | value");
    }

    #[test]
    fn normalize_converts_crlf() {
        assert_eq!(normalize_text("a\r\nb"), "a\nb");
    }

    #[test]
    fn extract_txt_reads_plain_text() {
        let (_dir, path) = write_temp("sample.txt", "hello   world");
        let doc = extract_file(&path).expect("extract");
        assert_eq!(doc.text, "hello world");
        assert_eq!(doc.source_kind, "txt");
    }

    #[test]
    fn extract_md_keeps_heading_and_bold_text() {
        let (_dir, path) = write_temp("sample.md", "# Title\n\nSome **bold** text\n");
        let doc = extract_file(&path).expect("extract");
        assert!(doc.text.contains("Title"));
        assert!(doc.text.contains("bold"));
        assert_eq!(doc.source_kind, "md");
    }

    #[test]
    fn extract_md_renders_list_items() {
        let (_dir, path) = write_temp("sample.md", "- first\n- second\n");
        let doc = extract_file(&path).expect("extract");
        assert!(doc.text.contains("- first"));
        assert!(doc.text.contains("- second"));
    }

    #[test]
    fn extract_html_drops_script_and_style() {
        let (_dir, path) = write_temp(
            "sample.html",
            "<html><body><p>keep</p><script>drop()</script><style>.x{}</style></body></html>",
        );
        let doc = extract_file(&path).expect("extract");
        assert!(doc.text.contains("keep"));
        assert!(!doc.text.contains("drop()"));
        assert!(!doc.text.contains(".x{}"));
    }

    #[test]
    fn unsupported_suffix_is_rejected() {
        let (_dir, path) = write_temp("sample.csv", "a,b");
        let err = extract_file(&path).expect_err("must reject");
        assert!(err.to_string().contains("Unsupported file type"));
    }

    #[test]
    fn pdf_is_rejected_as_unsupported() {
        let (_dir, path) = write_temp("sample.pdf", "%PDF-1.4");
        let err = extract_file(&path).expect_err("pdf is out of scope for v1");
        assert!(err.to_string().contains("Unsupported file type"));
    }

    #[test]
    fn missing_file_is_reported() {
        let err = extract_file(Path::new("/tmp/definitely-missing-vecstash.txt"))
            .expect_err("must fail");
        assert!(err.to_string().contains("File not found"));
    }

    #[test]
    fn md_table_with_two_columns_becomes_key_value() {
        let raw = "| name | value |\n|---|---|\n| a | 1 |\n";
        let out = linearize_md_tables(raw);
        assert!(out.contains("name: a"));
        assert!(out.contains("value: 1"));
    }

    #[test]
    fn md_table_with_three_columns_labels_every_cell() {
        let raw = "| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |\n";
        let out = linearize_md_tables(raw);
        assert!(out.contains("a: 1"));
        assert!(out.contains("b: 2"));
        assert!(out.contains("c: 3"));
    }

    #[test]
    fn md_table_cells_lose_backticks_and_bold() {
        let raw = "| name | value |\n|---|---|\n| `code` | **strong** |\n";
        let out = linearize_md_tables(raw);
        assert!(out.contains("name: code"));
        assert!(out.contains("value: strong"));
    }

    #[test]
    fn text_without_tables_is_untouched() {
        let raw = "just a line\nanother line";
        assert_eq!(linearize_md_tables(raw), raw);
    }

    #[test]
    fn md_table_keeps_surrounding_text() {
        let raw = "before\n\n| k | v |\n|---|---|\n| a | 1 |\n\nafter";
        let out = linearize_md_tables(raw);
        assert!(out.contains("before"));
        assert!(out.contains("after"));
        assert!(out.contains("k: a"));
    }

    #[test]
    fn html_table_with_headers_becomes_key_value() {
        let html = "<table><tr><th>name</th><th>value</th></tr><tr><td>a</td><td>1</td></tr></table>";
        let out = linearize_html_tables(html);
        assert!(out.contains("a: 1"));
    }

    #[test]
    fn html_table_without_headers_uses_first_row() {
        let html = "<table><tr><td>name</td><td>value</td></tr><tr><td>a</td><td>1</td></tr></table>";
        let out = linearize_html_tables(html);
        assert!(out.contains("a: 1"));
    }

    #[test]
    fn html_table_with_three_columns_labels_every_cell() {
        let html = "<table><tr><th>a</th><th>b</th><th>c</th></tr><tr><td>1</td><td>2</td><td>3</td></tr></table>";
        let out = linearize_html_tables(html);
        assert!(out.contains("a: 1"));
        assert!(out.contains("b: 2"));
        assert!(out.contains("c: 3"));
    }

    #[test]
    fn md_file_with_table_extracts_linear_text() {
        let (_dir, path) = write_temp("t.md", "# Title\n\n| k | v |\n|---|---|\n| a | 1 |\n");
        let doc = extract_file(&path).expect("extract");
        assert!(doc.text.contains("k: a"));
        assert!(doc.text.contains("v: 1"));
    }

    #[test]
    fn html_file_with_table_extracts_linear_text() {
        let (_dir, path) = write_temp(
            "t.html",
            "<html><body><table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table></body></html>",
        );
        let doc = extract_file(&path).expect("extract");
        assert!(doc.text.contains("a: 1"));
    }

    #[test]
    fn same_content_yields_same_hash() {
        let (_dir_a, path_a) = write_temp("a.txt", "same content");
        let (_dir_b, path_b) = write_temp("b.txt", "same content");
        let doc_a = extract_file(&path_a).expect("extract");
        let doc_b = extract_file(&path_b).expect("extract");
        assert_eq!(doc_a.content_hash, doc_b.content_hash);
        assert_ne!(doc_a.document_id, doc_b.document_id);
    }
}
