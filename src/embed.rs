use crate::config::AppConfig;
use crate::output::Format;
use anyhow::{Result, bail};
use std::path::PathBuf;
use std::process::ExitCode;

pub fn cmd_models_show(_config: &AppConfig, _format: Format) -> Result<ExitCode> {
    bail!("Command 'models show' is not implemented yet.")
}

pub fn cmd_models_validate(
    _config: &AppConfig,
    _offline_only: bool,
    _format: Format,
) -> Result<ExitCode> {
    bail!("Command 'models validate' is not implemented yet.")
}

pub fn cmd_models_bootstrap(_config: &AppConfig, _format: Format) -> Result<ExitCode> {
    bail!("Command 'models bootstrap' is not implemented yet.")
}

pub fn cmd_ingest(_config: &AppConfig, _inputs: &[PathBuf], _format: Format) -> Result<ExitCode> {
    bail!("Command 'ingest' is not implemented yet.")
}

pub fn cmd_search(
    _config: &AppConfig,
    _query: &str,
    _limit: usize,
    _format: Format,
) -> Result<ExitCode> {
    bail!("Command 'search' is not implemented yet.")
}
