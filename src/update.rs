use crate::output::Format;
use anyhow::{Result, bail};
use std::process::ExitCode;

pub fn cmd_update(_check: bool, _format: Format) -> Result<ExitCode> {
    bail!("Command 'update' is not implemented yet.")
}
