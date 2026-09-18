use crate::chunk;
use crate::config::AppConfig;
use crate::embed::{self, Embedder};
use crate::extract::{self, ExtractedDocument};
use crate::output::{self, Format};
use crate::store::{SearchHit, Store};
use anyhow::Result;
use comfy_table::{Table, presets};
use owo_colors::OwoColorize;
use rayon::prelude::*;
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

#[derive(Serialize)]
struct IngestReport {
    document_id: String,
    source_path: String,
    source_kind: String,
    chunks: usize,
    indexed: bool,
}

fn extract_all(inputs: &[PathBuf]) -> (Vec<ExtractedDocument>, Vec<String>) {
    let results: Vec<Result<ExtractedDocument>> = inputs
        .par_iter()
        .map(|path| extract::extract_file(path))
        .collect();

    let mut documents = Vec::new();
    let mut failures = Vec::new();
    for result in results {
        match result {
            Ok(document) => documents.push(document),
            Err(e) => failures.push(e.to_string()),
        }
    }
    (documents, failures)
}

pub fn cmd_ingest(config: &AppConfig, inputs: &[PathBuf], format: Format) -> Result<ExitCode> {
    let (documents, failures) = extract_all(inputs);
    for failure in &failures {
        output::print_warning(failure);
    }

    if documents.is_empty() {
        output::print_warning("No documents were extracted.");
        return Ok(ExitCode::from(1));
    }

    let mut embedder = Embedder::load(config)?;
    let tokenizer = embed::load_chunk_tokenizer(config)?;

    let mut store = Store::open(&config.paths.sqlite_path)?;
    store.ensure_dimension(embedder.dim())?;

    let mut reports = Vec::with_capacity(documents.len());
    for document in &documents {
        store.upsert_document(document)?;

        let chunks = chunk::chunk_with_tokenizer(
            document,
            tokenizer.clone(),
            config.runtime.chunk_tokens,
            config.runtime.chunk_overlap,
        )?;

        let mut texts = Vec::with_capacity(chunks.len());
        for item in &chunks {
            texts.push(item.text.clone());
        }

        let indexed = match embedder.embed(&texts, config.runtime.max_batch_size) {
            Ok(vectors) => {
                store.replace_chunks(&document.document_id, &chunks, &vectors)?;
                true
            }
            Err(e) => {
                tracing::warn!(event = "embed_failed", path = %document.source_path, error = %e);
                output::print_warning(&format!(
                    "vector indexing failed for {}, metadata saved.",
                    document.source_path
                ));
                false
            }
        };

        reports.push(IngestReport {
            document_id: document.document_id.clone(),
            source_path: document.source_path.clone(),
            source_kind: document.source_kind.clone(),
            chunks: chunks.len(),
            indexed,
        });
    }

    match format {
        Format::Json => output::print_json(&reports)?,
        Format::Human => {
            let mut table = Table::new();
            table.load_style(presets::UTF8_FULL);
            table.set_header(vec!["File", "Kind", "Chunks", "Indexed"]);
            for report in &reports {
                let IngestReport {
                    document_id: _,
                    source_path,
                    source_kind,
                    chunks,
                    indexed,
                } = report;
                table.add_row(vec![
                    file_label(source_path),
                    source_kind.clone(),
                    chunks.to_string(),
                    indexed.to_string(),
                ]);
            }
            output::print_line(&table.to_string());
        }
    }

    Ok(ExitCode::SUCCESS)
}

fn file_label(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|v| v.to_string_lossy().into_owned())
        .unwrap_or_else(|| path.to_string())
}

#[derive(Serialize)]
struct SearchReport {
    score: f32,
    document_id: String,
    source_path: String,
    chunk_index: i64,
    chunk_text: String,
}

pub fn cmd_search(
    config: &AppConfig,
    query: &str,
    limit: usize,
    format: Format,
) -> Result<ExitCode> {
    let store = Store::open(&config.paths.sqlite_path)?;
    if store.chunks_count()? == 0 {
        output::print_warning("No documents indexed yet. Run 'vecstash ingest <files>' first.");
        return Ok(ExitCode::from(1));
    }

    let mut embedder = Embedder::load(config)?;
    let vectors = embedder.embed(&[query.to_string()], 1)?;
    let Some(query_vector) = vectors.first() else {
        output::print_warning("Query produced no embedding.");
        return Ok(ExitCode::from(1));
    };

    let hits = store.search(query_vector, limit)?;

    let mut reports = Vec::with_capacity(hits.len());
    for hit in &hits {
        let SearchHit {
            score,
            document_id,
            source_path,
            chunk_text,
            chunk_index,
        } = hit;
        reports.push(SearchReport {
            score: *score,
            document_id: document_id.clone(),
            source_path: source_path.clone(),
            chunk_index: *chunk_index,
            chunk_text: chunk_text.clone(),
        });
    }

    match format {
        Format::Json => output::print_json(&reports)?,
        Format::Human => {
            if reports.is_empty() {
                output::print_warning("No results.");
                return Ok(ExitCode::SUCCESS);
            }
            let skin = termimad::MadSkin::default();
            for report in &reports {
                let score = format!("{:.3}", report.score);
                let label = file_label(&report.source_path);
                let header = if report.score > 0.8 {
                    format!("{} {}", score.green().bold(), label.bold())
                } else if report.score > 0.5 {
                    format!("{} {}", score.yellow().bold(), label.bold())
                } else {
                    format!("{} {}", score.red().bold(), label.bold())
                };
                output::print_line(&header);
                output::print_line(&skin.text(&report.chunk_text, None).to_string());
            }
        }
    }

    Ok(ExitCode::SUCCESS)
}
