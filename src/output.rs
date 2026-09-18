use anyhow::Error;
use owo_colors::OwoColorize;
use serde::Serialize;
use std::io::{self, Write};

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Format {
    Json,
    Human,
}

impl Format {
    pub fn from_flag(json: bool) -> Self {
        if json { Format::Json } else { Format::Human }
    }
}

pub fn print_json<T: Serialize>(value: &T) -> anyhow::Result<()> {
    let line = serde_json::to_string(value)?;
    let mut out = io::stdout().lock();
    writeln!(out, "{line}")?;
    Ok(())
}

pub fn print_error(error: &Error) {
    let mut err = io::stderr().lock();
    let _ = writeln!(err, "{} {error}", "Error:".red().bold());
    for cause in error.chain().skip(1) {
        let _ = writeln!(err, "  caused by: {cause}");
    }
}

pub fn print_warning(message: &str) {
    let mut err = io::stderr().lock();
    let _ = writeln!(err, "{} {message}", "Warning:".yellow().bold());
}

pub fn print_success(message: &str) {
    let mut err = io::stderr().lock();
    let _ = writeln!(err, "{}", message.green());
}

pub fn print_line(message: &str) {
    let mut err = io::stderr().lock();
    let _ = writeln!(err, "{message}");
}
