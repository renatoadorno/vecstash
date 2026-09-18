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
struct IndexedDocument {
    document_id: String,
    source_path: String,
    source_kind: String,
    chunks: usize,
    indexed: bool,
}

#[derive(Serialize)]
struct FailedDocument {
    source_path: String,
    error: String,
}

#[derive(Serialize)]
struct IngestReport {
    indexed: Vec<IndexedDocument>,
    failed: Vec<FailedDocument>,
}

fn extract_all(inputs: &[PathBuf]) -> (Vec<ExtractedDocument>, Vec<FailedDocument>) {
    let results: Vec<(PathBuf, Result<ExtractedDocument>)> = inputs
        .par_iter()
        .map(|path| (path.clone(), extract::extract_file(path)))
        .collect();

    let mut documents = Vec::new();
    let mut failed = Vec::new();
    for (path, result) in results {
        match result {
            Ok(document) => documents.push(document),
            Err(e) => failed.push(FailedDocument {
                source_path: path.display().to_string(),
                error: e.to_string(),
            }),
        }
    }
    (documents, failed)
}

fn emit_ingest(report: &IngestReport, format: Format) -> Result<()> {
    match format {
        Format::Json => output::print_json(report)?,
        Format::Human => {
            for failure in &report.failed {
                output::print_warning(&format!("{}: {}", failure.source_path, failure.error));
            }
            if report.indexed.is_empty() {
                return Ok(());
            }
            let mut table = Table::new();
            table.load_style(presets::UTF8_FULL);
            table.set_header(vec!["File", "Kind", "Chunks", "Indexed"]);
            for document in &report.indexed {
                let IndexedDocument {
                    document_id: _,
                    source_path,
                    source_kind,
                    chunks,
                    indexed,
                } = document;
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
    Ok(())
}

pub fn cmd_ingest(config: &AppConfig, inputs: &[PathBuf], format: Format) -> Result<ExitCode> {
    let (documents, failed) = extract_all(inputs);

    if documents.is_empty() {
        let report = IngestReport {
            indexed: Vec::new(),
            failed,
        };
        emit_ingest(&report, format)?;
        if let Format::Human = format {
            output::print_warning("No documents were extracted.");
        }
        return Ok(ExitCode::from(1));
    }

    let mut embedder = Embedder::load(config)?;
    let tokenizer = embed::load_chunk_tokenizer(config)?;

    let mut store = Store::open(&config.paths.sqlite_path)?;
    store.ensure_dimension(embedder.dim()?)?;

    let mut indexed = Vec::with_capacity(documents.len());
    for document in &documents {
        store.upsert_document(document)?;

        let chunks = chunk::chunk_with_tokenizer(
            document,
            &tokenizer,
            config.runtime.chunk_tokens,
            config.runtime.chunk_overlap,
        )?;

        let mut texts = Vec::with_capacity(chunks.len());
        for item in &chunks {
            texts.push(item.text.clone());
        }

        let embedded = match embedder.embed(&texts, config.runtime.max_batch_size) {
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

        indexed.push(IndexedDocument {
            document_id: document.document_id.clone(),
            source_path: document.source_path.clone(),
            source_kind: document.source_kind.clone(),
            chunks: chunks.len(),
            indexed: embedded,
        });
    }

    let mut all_indexed = true;
    for document in &indexed {
        if !document.indexed {
            all_indexed = false;
        }
    }

    let report = IngestReport { indexed, failed };
    let partial = !report.failed.is_empty() || !all_indexed;
    emit_ingest(&report, format)?;

    tracing::info!(
        event = "ingest_finished",
        documents = report.indexed.len(),
        failed = report.failed.len(),
    );

    if partial {
        return Ok(ExitCode::from(1));
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
struct SearchResult {
    score: f32,
    document_id: String,
    source_path: String,
    chunk_index: i64,
    chunk_text: String,
}

fn empty_index(format: Format) -> Result<ExitCode> {
    match format {
        Format::Json => output::print_json(&serde_json::json!({
            "status": "empty_index",
            "hint": "Run 'vecstash ingest <files>' first.",
            "results": [],
        }))?,
        Format::Human => {
            output::print_warning("No documents indexed yet. Run 'vecstash ingest <files>' first.")
        }
    }
    Ok(ExitCode::from(1))
}

pub fn cmd_search(
    config: &AppConfig,
    query: &str,
    limit: usize,
    format: Format,
) -> Result<ExitCode> {
    let store = Store::open(&config.paths.sqlite_path)?;
    if store.chunks_count()? == 0 {
        return empty_index(format);
    }

    let mut embedder = Embedder::load(config)?;
    let vectors = embedder.embed(&[query.to_string()], 1)?;
    let Some(query_vector) = vectors.first() else {
        return empty_index(format);
    };

    let hits = store.search(query_vector, limit)?;

    let mut results = Vec::with_capacity(hits.len());
    for hit in &hits {
        let SearchHit {
            score,
            document_id,
            source_path,
            chunk_text,
            chunk_index,
        } = hit;
        results.push(SearchResult {
            score: *score,
            document_id: document_id.clone(),
            source_path: source_path.clone(),
            chunk_index: *chunk_index,
            chunk_text: chunk_text.clone(),
        });
    }

    match format {
        Format::Json => output::print_json(&results)?,
        Format::Human => {
            if results.is_empty() {
                output::print_warning("No results.");
                return Ok(ExitCode::SUCCESS);
            }
            let skin = termimad::MadSkin::default();
            for result in &results {
                let score = format!("{:.3}", result.score);
                let label = file_label(&result.source_path);
                let header = if result.score > 0.8 {
                    format!("{} {}", score.green().bold(), label.bold())
                } else if result.score > 0.5 {
                    format!("{} {}", score.yellow().bold(), label.bold())
                } else {
                    format!("{} {}", score.red().bold(), label.bold())
                };
                output::print_line(&header);
                output::print_line(&skin.text(&result.chunk_text, None).to_string());
            }
        }
    }

    Ok(ExitCode::SUCCESS)
}
