mod chunk;
mod cli;
mod config;
mod embed;
mod extract;
mod logging;
mod output;
mod pipeline;
mod store;
mod update;

use std::process::ExitCode;

fn main() -> ExitCode {
    match cli::run() {
        Ok(code) => code,
        Err(e) => {
            output::print_error(&e);
            ExitCode::from(1)
        }
    }
}
