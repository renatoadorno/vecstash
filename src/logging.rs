use anyhow::{Context, Result};
use std::fs::{self, OpenOptions};
use std::path::Path;
use tracing_subscriber::EnvFilter;
use tracing_subscriber::prelude::*;

pub fn init(log_path: &Path) -> Result<()> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("Cannot create log directory {}", parent.display()))?;
    }

    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_path)
        .with_context(|| format!("Cannot open log file {}", log_path.display()))?;

    let filter = EnvFilter::try_from_env("VECSTASH_LOG").unwrap_or_else(|_| EnvFilter::new("info"));

    let layer = tracing_subscriber::fmt::layer()
        .json()
        .flatten_event(true)
        .with_current_span(false)
        .with_span_list(false)
        .with_writer(file);

    let _ = tracing_subscriber::registry()
        .with(filter)
        .with(layer)
        .try_init();

    Ok(())
}
