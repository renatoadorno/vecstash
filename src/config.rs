use anyhow::{Context, Result, anyhow, bail};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Component, Path, PathBuf};

pub const DEFAULT_MODEL: &str = "Xenova/bge-m3";
pub const DEFAULT_ONNX_FILE: &str = "onnx/model_fp16.onnx";
pub const DEFAULT_CHUNK_TOKENS: usize = 512;
pub const DEFAULT_CHUNK_OVERLAP: usize = 64;
pub const DEFAULT_MAX_BATCH_SIZE: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct AppName(pub String);

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ModelId(pub String);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ExecutionProvider {
    Cpu,
    CoreMl,
}

impl ExecutionProvider {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExecutionProvider::Cpu => "cpu",
            ExecutionProvider::CoreMl => "coreml",
        }
    }
}

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub app: AppSection,
    pub model: ModelSection,
    pub paths: PathsSection,
    pub runtime: RuntimeSection,
}

#[derive(Debug, Clone)]
pub struct AppSection {
    pub name: AppName,
}

#[derive(Debug, Clone)]
pub struct ModelSection {
    pub name: ModelId,
    pub onnx_file: String,
    pub cache_dir: PathBuf,
    pub execution_provider: ExecutionProvider,
}

#[derive(Debug, Clone)]
pub struct PathsSection {
    pub data_dir: PathBuf,
    pub sqlite_path: PathBuf,
    pub log_path: PathBuf,
}

#[derive(Debug, Clone)]
pub struct RuntimeSection {
    pub max_batch_size: usize,
    pub chunk_tokens: usize,
    pub chunk_overlap: usize,
}

#[derive(Debug, Default, Deserialize)]
struct RawConfig {
    #[serde(default)]
    app: RawApp,
    #[serde(default)]
    model: RawModel,
    #[serde(default)]
    paths: RawPaths,
    #[serde(default)]
    runtime: RawRuntime,
}

#[derive(Debug, Default, Deserialize)]
struct RawApp {
    name: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct RawModel {
    name: Option<String>,
    onnx_file: Option<String>,
    cache_dir: Option<String>,
    execution_provider: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct RawPaths {
    data_dir: Option<String>,
    sqlite_path: Option<String>,
    log_path: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct RawRuntime {
    max_batch_size: Option<usize>,
    chunk_tokens: Option<usize>,
    chunk_overlap: Option<usize>,
}

pub fn default_data_dir() -> Result<PathBuf> {
    let Some(dirs) = directories::BaseDirs::new() else {
        bail!("Cannot determine the home directory.");
    };
    Ok(dirs.home_dir().join(".vecstash"))
}

pub fn default_config_path() -> Result<PathBuf> {
    Ok(default_data_dir()?.join("config.toml"))
}

fn expand(raw: &str) -> Result<PathBuf> {
    let raw = raw.trim();
    if raw.is_empty() {
        bail!("Path must not be empty.");
    }
    let expanded = if let Some(rest) = raw.strip_prefix("~/") {
        let Some(dirs) = directories::BaseDirs::new() else {
            bail!("Cannot determine the home directory.");
        };
        dirs.home_dir().join(rest)
    } else {
        PathBuf::from(raw)
    };
    Ok(expanded)
}

fn reject_parent_dir(path: &Path, field: &str) -> Result<()> {
    for component in path.components() {
        match component {
            Component::ParentDir => {
                bail!("{field} must not contain '..'.");
            }
            Component::Normal(_)
            | Component::CurDir
            | Component::RootDir
            | Component::Prefix(_) => {}
        }
    }
    Ok(())
}

fn ensure_within(base: &Path, target: &Path, field: &str) -> Result<()> {
    reject_parent_dir(target, field)?;
    if target.starts_with(base) {
        return Ok(());
    }
    Err(anyhow!("{field} must be inside paths.data_dir."))
}

fn relative_repo_file(value: Option<String>, default: &str, field: &str) -> Result<String> {
    let value = non_empty(value, default, field)?;
    for component in Path::new(&value).components() {
        match component {
            Component::Normal(_) | Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                bail!("{field} must be a relative path inside the model repository, without '..'.");
            }
        }
    }
    Ok(value)
}

fn non_empty(value: Option<String>, default: &str, field: &str) -> Result<String> {
    let value = value.unwrap_or_else(|| default.to_string());
    if value.trim().is_empty() {
        bail!("{field} must be a non-empty string.");
    }
    Ok(value)
}

fn positive(value: Option<usize>, default: usize, field: &str) -> Result<usize> {
    let value = value.unwrap_or(default);
    if value == 0 {
        bail!("{field} must be a positive integer.");
    }
    Ok(value)
}

fn parse_provider(value: Option<String>) -> Result<ExecutionProvider> {
    let Some(value) = value else {
        return Ok(ExecutionProvider::Cpu);
    };
    match value.trim().to_lowercase().as_str() {
        "cpu" => Ok(ExecutionProvider::Cpu),
        "coreml" => Ok(ExecutionProvider::CoreMl),
        other => Err(anyhow!(
            "model.execution_provider must be 'cpu' or 'coreml', got '{other}'"
        )),
    }
}

const LEGACY_KEYS: [(&str, &str); 6] = [
    ("model", "backend"),
    ("model", "preload_on_start"),
    ("paths", "qdrant_path"),
    ("paths", "socket_path"),
    ("runtime", "max_concurrency"),
    ("runtime", "query_cache_size"),
];

/// A config written by vecstash 0.1.x parses cleanly here — unknown keys are ignored —
/// but leaves `model.name` pointing at a PyTorch-only repository, so the first
/// `models bootstrap` fails with a download error that never mentions the real cause.
fn reject_legacy_config(contents: &str) -> Result<()> {
    let Ok(value) = toml::from_str::<toml::Value>(contents) else {
        return Ok(());
    };
    for (section, key) in LEGACY_KEYS {
        let present = value
            .get(section)
            .and_then(|section| section.get(key))
            .is_some();
        if present {
            bail!(
                "This config was written by vecstash 0.1.x ('{section}.{key}' is no longer used). \
                 Move it aside and run any command to generate a new one."
            );
        }
    }
    Ok(())
}

pub fn parse(contents: &str) -> Result<AppConfig> {
    reject_legacy_config(contents)?;
    let raw: RawConfig = toml::from_str(contents).context("config.toml is not valid TOML")?;
    let RawConfig {
        app,
        model,
        paths,
        runtime,
    } = raw;

    let data_dir = match paths.data_dir {
        Some(value) => expand(&value)?,
        None => default_data_dir()?,
    };

    let sqlite_path = match paths.sqlite_path {
        Some(value) => expand(&value)?,
        None => data_dir.join("metadata.db"),
    };
    let log_path = match paths.log_path {
        Some(value) => expand(&value)?,
        None => data_dir.join("vecstash.log"),
    };
    let cache_dir = match model.cache_dir {
        Some(value) => expand(&value)?,
        None => data_dir.join("models"),
    };

    ensure_within(&data_dir, &sqlite_path, "paths.sqlite_path")?;
    ensure_within(&data_dir, &log_path, "paths.log_path")?;
    ensure_within(&data_dir, &cache_dir, "model.cache_dir")?;

    let chunk_tokens = positive(
        runtime.chunk_tokens,
        DEFAULT_CHUNK_TOKENS,
        "runtime.chunk_tokens",
    )?;
    let chunk_overlap = runtime.chunk_overlap.unwrap_or(DEFAULT_CHUNK_OVERLAP);
    if chunk_overlap >= chunk_tokens {
        bail!("runtime.chunk_overlap must be smaller than runtime.chunk_tokens.");
    }

    Ok(AppConfig {
        app: AppSection {
            name: AppName(non_empty(app.name, "vecstash", "app.name")?),
        },
        model: ModelSection {
            name: ModelId(non_empty(model.name, DEFAULT_MODEL, "model.name")?),
            onnx_file: relative_repo_file(model.onnx_file, DEFAULT_ONNX_FILE, "model.onnx_file")?,
            cache_dir,
            execution_provider: parse_provider(model.execution_provider)?,
        },
        paths: PathsSection {
            data_dir,
            sqlite_path,
            log_path,
        },
        runtime: RuntimeSection {
            max_batch_size: positive(
                runtime.max_batch_size,
                DEFAULT_MAX_BATCH_SIZE,
                "runtime.max_batch_size",
            )?,
            chunk_tokens,
            chunk_overlap,
        },
    })
}

pub fn render_default() -> String {
    format!(
        "[app]\n\
         name = \"vecstash\"\n\
         \n\
         [model]\n\
         name = \"{DEFAULT_MODEL}\"\n\
         onnx_file = \"{DEFAULT_ONNX_FILE}\"\n\
         execution_provider = \"cpu\"\n\
         \n\
         [paths]\n\
         data_dir = \"~/.vecstash\"\n\
         \n\
         [runtime]\n\
         max_batch_size = {DEFAULT_MAX_BATCH_SIZE}\n\
         chunk_tokens = {DEFAULT_CHUNK_TOKENS}\n\
         chunk_overlap = {DEFAULT_CHUNK_OVERLAP}\n"
    )
}

pub fn load(explicit: Option<&Path>) -> Result<AppConfig> {
    let path = match explicit {
        Some(path) => path.to_path_buf(),
        None => default_config_path()?,
    };

    if !path.exists() {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("Cannot create {}", parent.display()))?;
        }
        fs::write(&path, render_default())
            .with_context(|| format!("Cannot write {}", path.display()))?;
    }

    let contents =
        fs::read_to_string(&path).with_context(|| format!("Cannot read {}", path.display()))?;
    let config =
        parse(&contents).with_context(|| format!("Invalid config at {}", path.display()))?;

    create_private_dir(&config.paths.data_dir)?;
    create_private_dir(&config.model.cache_dir)?;

    Ok(config)
}

/// The data dir holds the full text of every ingested document.
fn create_private_dir(path: &Path) -> Result<()> {
    use std::os::unix::fs::DirBuilderExt;
    if path.exists() {
        return Ok(());
    }
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(path)
        .with_context(|| format!("Cannot create {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_parses() {
        let config = parse(&render_default()).expect("default config must parse");
        assert_eq!(config.app.name.0, "vecstash");
        assert_eq!(config.model.name.0, DEFAULT_MODEL);
        assert_eq!(config.model.execution_provider, ExecutionProvider::Cpu);
        assert_eq!(config.runtime.chunk_tokens, DEFAULT_CHUNK_TOKENS);
        assert_eq!(config.runtime.chunk_overlap, DEFAULT_CHUNK_OVERLAP);
        assert_eq!(config.runtime.max_batch_size, DEFAULT_MAX_BATCH_SIZE);
    }

    #[test]
    fn empty_config_uses_defaults() {
        let config = parse("").expect("empty config must fall back to defaults");
        assert_eq!(config.model.name.0, DEFAULT_MODEL);
        assert!(config.paths.sqlite_path.ends_with("metadata.db"));
        assert!(config.paths.log_path.ends_with("vecstash.log"));
        assert!(config.model.cache_dir.ends_with("models"));
    }

    #[test]
    fn derived_paths_live_inside_data_dir() {
        let config = parse("[paths]\ndata_dir = \"/tmp/vecstash-test\"\n").expect("must parse");
        assert_eq!(
            config.paths.sqlite_path,
            PathBuf::from("/tmp/vecstash-test/metadata.db")
        );
        assert_eq!(
            config.model.cache_dir,
            PathBuf::from("/tmp/vecstash-test/models")
        );
    }

    #[test]
    fn sqlite_path_outside_data_dir_is_rejected() {
        let err = parse("[paths]\ndata_dir = \"/tmp/a\"\nsqlite_path = \"/tmp/b/x.db\"\n")
            .expect_err("path outside data_dir must be rejected");
        assert!(err.to_string().contains("paths.sqlite_path"));
    }

    #[test]
    fn log_path_outside_data_dir_is_rejected() {
        let err = parse("[paths]\ndata_dir = \"/tmp/a\"\nlog_path = \"/tmp/b/x.log\"\n")
            .expect_err("path outside data_dir must be rejected");
        assert!(err.to_string().contains("paths.log_path"));
    }

    #[test]
    fn cache_dir_outside_data_dir_is_rejected() {
        let err = parse("[paths]\ndata_dir = \"/tmp/a\"\n\n[model]\ncache_dir = \"/tmp/b\"\n")
            .expect_err("cache_dir outside data_dir must be rejected");
        assert!(err.to_string().contains("model.cache_dir"));
    }

    #[test]
    fn legacy_python_config_is_rejected_with_a_clear_message() {
        let legacy = "[model]\nname = \"BAAI/bge-m3\"\nbackend = \"sentence_transformers\"\n\n\
                      [paths]\ndata_dir = \"/tmp/x\"\nqdrant_path = \"/tmp/x/qdrant\"\n";
        let err = parse(legacy).expect_err("a 0.1.x config must be rejected, not silently ignored");
        let message = err.to_string();
        assert!(message.contains("0.1.x"), "message was: {message}");
        assert!(message.contains("model.backend"), "message was: {message}");
    }

    #[test]
    fn legacy_runtime_keys_are_rejected() {
        let err = parse("[runtime]\nmax_concurrency = 4\n").expect_err("must be rejected");
        assert!(err.to_string().contains("runtime.max_concurrency"));
    }

    #[test]
    fn parent_dir_escape_is_rejected() {
        let err =
            parse("[paths]\ndata_dir = \"/tmp/a\"\nsqlite_path = \"/tmp/a/../../etc/x.db\"\n")
                .expect_err("'..' must not escape data_dir");
        assert!(err.to_string().contains("paths.sqlite_path"));
    }

    #[test]
    fn parent_dir_escape_in_log_path_is_rejected() {
        let err = parse("[paths]\ndata_dir = \"/tmp/a\"\nlog_path = \"/tmp/a/../../etc/x.log\"\n")
            .expect_err("'..' must not escape data_dir");
        assert!(err.to_string().contains("paths.log_path"));
    }

    #[test]
    fn absolute_onnx_file_is_rejected() {
        let err = parse("[model]\nonnx_file = \"/Users/someone/Library/LaunchAgents/x.plist\"\n")
            .expect_err("onnx_file must be a relative path inside the repo");
        assert!(err.to_string().contains("model.onnx_file"));
    }

    #[test]
    fn onnx_file_with_parent_dir_is_rejected() {
        let err = parse("[model]\nonnx_file = \"../../../etc/passwd\"\n")
            .expect_err("onnx_file must not contain '..'");
        assert!(err.to_string().contains("model.onnx_file"));
    }

    #[test]
    fn relative_onnx_file_is_accepted() {
        let config = parse("[model]\nonnx_file = \"onnx/model_fp16.onnx\"\n").expect("must parse");
        assert_eq!(config.model.onnx_file, "onnx/model_fp16.onnx");
    }

    #[test]
    fn unknown_execution_provider_is_rejected() {
        let err = parse("[model]\nexecution_provider = \"cuda\"\n")
            .expect_err("unknown provider must be rejected");
        assert!(err.to_string().contains("execution_provider"));
    }

    #[test]
    fn coreml_execution_provider_is_accepted() {
        let config = parse("[model]\nexecution_provider = \"coreml\"\n").expect("must parse");
        assert_eq!(config.model.execution_provider, ExecutionProvider::CoreMl);
    }

    #[test]
    fn zero_batch_size_is_rejected() {
        let err = parse("[runtime]\nmax_batch_size = 0\n").expect_err("zero must be rejected");
        assert!(err.to_string().contains("max_batch_size"));
    }

    #[test]
    fn overlap_not_smaller_than_chunk_is_rejected() {
        let err = parse("[runtime]\nchunk_tokens = 100\nchunk_overlap = 100\n")
            .expect_err("overlap >= chunk_tokens must be rejected");
        assert!(err.to_string().contains("chunk_overlap"));
    }

    #[test]
    fn empty_app_name_is_rejected() {
        let err = parse("[app]\nname = \"  \"\n").expect_err("blank name must be rejected");
        assert!(err.to_string().contains("app.name"));
    }
}
