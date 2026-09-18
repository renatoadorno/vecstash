use crate::config::{self, AppConfig};
use crate::output::{self, Format};
use anyhow::Result;
use clap::{CommandFactory, Parser, Subcommand};
use clap_complete::Shell;
use std::io;
use std::path::PathBuf;
use std::process::ExitCode;

pub const EXIT_VALIDATION_FAILED: u8 = 2;

#[derive(Parser)]
#[command(
    name = "vecstash",
    version,
    about = "Local semantic storage and search for macOS",
    arg_required_else_help = true
)]
struct Cli {
    #[arg(long, global = true, value_name = "PATH")]
    config: Option<PathBuf>,

    #[arg(long, global = true)]
    json: bool,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Show configuration, storage and index state
    Status,

    /// Inspect and manage the embedding model
    Models {
        #[command(subcommand)]
        command: ModelsCommand,
    },

    /// Extract, chunk, embed and index files
    Ingest {
        #[arg(required = true, value_name = "FILE")]
        inputs: Vec<PathBuf>,
    },

    /// Search the index semantically
    Search {
        query: String,

        #[arg(long, short = 'n', default_value_t = 5)]
        limit: usize,
    },

    /// Check for and install a newer release
    Update {
        #[arg(long)]
        check: bool,
    },

    /// Print the version
    Version,

    /// Show on-disk size of the index
    Storage,

    /// Delete the index and start over
    Reset {
        #[arg(long)]
        force: bool,
    },

    /// Print a shell completion script
    Completions {
        #[arg(value_enum)]
        shell: Shell,
    },

    /// Print the roff manual page
    Manpage,
}

#[derive(Subcommand)]
enum ModelsCommand {
    /// Show the configured model
    Show,

    /// Verify the model is usable
    Validate {
        #[arg(long)]
        offline_only: bool,
    },

    /// Download the model into the local cache
    Bootstrap,
}

pub fn run() -> Result<ExitCode> {
    let Cli {
        config: config_path,
        json,
        command,
    } = Cli::parse();

    let format = Format::from_flag(json);

    match &command {
        Command::Version => return version(format),
        Command::Completions { shell } => return completions(*shell),
        Command::Manpage => return manpage(),
        Command::Status
        | Command::Models { .. }
        | Command::Ingest { .. }
        | Command::Search { .. }
        | Command::Update { .. }
        | Command::Storage
        | Command::Reset { .. } => {}
    }

    let config = config::load(config_path.as_deref())?;
    crate::logging::init(&config.paths.log_path)?;

    match command {
        Command::Version | Command::Completions { .. } | Command::Manpage => {
            unreachable!("handled above")
        }
        Command::Status => crate::store::cmd_status(&config, format),
        Command::Storage => crate::store::cmd_storage(&config, format),
        Command::Reset { force } => crate::store::cmd_reset(&config, force, format),
        Command::Models { command } => models(&config, command, format),
        Command::Ingest { inputs } => crate::pipeline::cmd_ingest(&config, &inputs, format),
        Command::Search { query, limit } => {
            crate::pipeline::cmd_search(&config, &query, limit, format)
        }
        Command::Update { check } => crate::update::cmd_update(check, format),
    }
}

fn models(config: &AppConfig, command: ModelsCommand, format: Format) -> Result<ExitCode> {
    match command {
        ModelsCommand::Show => crate::embed::cmd_models_show(config, format),
        ModelsCommand::Validate { offline_only } => {
            crate::embed::cmd_models_validate(config, offline_only, format)
        }
        ModelsCommand::Bootstrap => crate::embed::cmd_models_bootstrap(config, format),
    }
}

fn completions(shell: Shell) -> Result<ExitCode> {
    let mut command = Cli::command();
    let name = command.get_name().to_string();
    clap_complete::generate(shell, &mut command, name, &mut io::stdout());
    Ok(ExitCode::SUCCESS)
}

fn manpage() -> Result<ExitCode> {
    clap_mangen::Man::new(Cli::command()).render(&mut io::stdout())?;
    Ok(ExitCode::SUCCESS)
}

fn version(format: Format) -> Result<ExitCode> {
    let version = env!("CARGO_PKG_VERSION");
    match format {
        Format::Json => output::print_json(&serde_json::json!({ "version": version }))?,
        Format::Human => output::print_line(&format!("vecstash v{version}")),
    }
    Ok(ExitCode::SUCCESS)
}
