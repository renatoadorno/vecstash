use crate::config::{AppConfig, ExecutionProvider};
use crate::output::{self, Format};
use anyhow::{Context, Result, anyhow, bail};
use comfy_table::{Table, presets};
use hf_hub::{Cache, Repo, RepoType, api::sync::ApiBuilder};
use ort::execution_providers::{CPU, CoreML};
use ort::session::{Session, builder::GraphOptimizationLevel};
use ort::value::Tensor;
use serde::Serialize;
use std::path::PathBuf;
use std::process::ExitCode;
use tokenizers::{PaddingParams, PaddingStrategy, Tokenizer, TruncationParams};

const TOKENIZER_FILE: &str = "tokenizer.json";

/// The chunker sizes text without special tokens; the embedder encodes with them.
/// Without this slack a chunk that lands exactly on the cap loses its last tokens.
const SPECIAL_TOKEN_BUDGET: usize = 2;

fn hub_dir(config: &AppConfig) -> PathBuf {
    config.model.cache_dir.join("hub")
}

fn repo(config: &AppConfig) -> Repo {
    Repo::new(config.model.name.0.clone(), RepoType::Model)
}

fn cached_file(config: &AppConfig, file: &str) -> Option<PathBuf> {
    Cache::new(hub_dir(config)).repo(repo(config)).get(file)
}

fn download_file(config: &AppConfig, file: &str) -> Result<PathBuf> {
    let api = ApiBuilder::new()
        .with_cache_dir(hub_dir(config))
        .build()
        .context("Cannot initialise the HuggingFace client")?;
    api.repo(repo(config)).get(file).with_context(|| {
        format!(
            "Cannot download '{file}' for model '{}'",
            config.model.name.0
        )
    })
}

fn resolve_file(config: &AppConfig, file: &str, offline_only: bool) -> Result<PathBuf> {
    if let Some(path) = cached_file(config, file) {
        return Ok(path);
    }
    if offline_only {
        bail!(
            "Model '{}' is missing '{file}' in the local cache. \
             Run 'vecstash models bootstrap' to download it.",
            config.model.name.0
        );
    }
    download_file(config, file)
}

pub struct Embedder {
    session: Session,
    tokenizer: Tokenizer,
    dim: Option<usize>,
}

impl Embedder {
    pub fn load(config: &AppConfig) -> Result<Self> {
        let tokenizer_path = resolve_file(config, TOKENIZER_FILE, true)?;
        let model_path = resolve_file(config, &config.model.onnx_file, true)?;

        let mut tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| anyhow!("Cannot load tokenizer: {e}"))?;

        let max_length = config.runtime.chunk_tokens.max(64) + SPECIAL_TOKEN_BUDGET;
        tokenizer
            .with_padding(Some(PaddingParams {
                strategy: PaddingStrategy::BatchLongest,
                ..PaddingParams::default()
            }))
            .with_truncation(Some(TruncationParams {
                max_length,
                ..TruncationParams::default()
            }))
            .map_err(|e| anyhow!("Cannot configure tokenizer truncation: {e}"))?;

        let mut builder =
            Session::builder().map_err(|e| anyhow!("Cannot create ONNX session builder: {e}"))?;
        builder = match config.model.execution_provider {
            ExecutionProvider::Cpu => builder
                .with_execution_providers([CPU::default().build()])
                .map_err(|e| anyhow!("Cannot enable the CPU execution provider: {e}"))?,
            ExecutionProvider::CoreMl => builder
                .with_execution_providers([CoreML::default().build()])
                .map_err(|e| anyhow!("Cannot enable the CoreML execution provider: {e}"))?,
        };

        let session = builder
            .with_optimization_level(GraphOptimizationLevel::Level3)
            .map_err(|e| anyhow!("Cannot set the optimization level: {e}"))?
            .commit_from_file(&model_path)
            .map_err(|e| anyhow!("Cannot load ONNX model {}: {e}", model_path.display()))?;

        Ok(Embedder {
            session,
            tokenizer,
            dim: None,
        })
    }

    /// Runs one short forward pass the first time it is called. `search` never needs this,
    /// so probing eagerly in `load` would double the model passes on the hottest command.
    pub fn dim(&mut self) -> Result<usize> {
        if let Some(dim) = self.dim {
            return Ok(dim);
        }
        let probe = self.forward(&["dimension probe".to_string()])?;
        let Some(first) = probe.first() else {
            bail!("Model returned no embedding for the dimension probe.");
        };
        let dim = first.len();
        self.dim = Some(dim);
        Ok(dim)
    }

    fn forward(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        let encodings = self
            .tokenizer
            .encode_batch(texts.to_vec(), true)
            .map_err(|e| anyhow!("Tokenization failed: {e}"))?;

        let batch = encodings.len();
        let seq = encodings[0].get_ids().len();

        let mut input_ids: Vec<i64> = Vec::with_capacity(batch * seq);
        let mut attention_mask: Vec<i64> = Vec::with_capacity(batch * seq);
        for encoding in &encodings {
            for id in encoding.get_ids() {
                input_ids.push(i64::from(*id));
            }
            for mask in encoding.get_attention_mask() {
                attention_mask.push(i64::from(*mask));
            }
        }

        let shape = [batch as i64, seq as i64];
        let ids_tensor = Tensor::from_array((shape, input_ids))?;
        let mask_tensor = Tensor::from_array((shape, attention_mask))?;

        let mut wants_token_type_ids = false;
        for input in self.session.inputs() {
            if input.name() == "token_type_ids" {
                wants_token_type_ids = true;
            }
        }

        let outputs = if wants_token_type_ids {
            let token_type_ids = vec![0_i64; batch * seq];
            let type_tensor = Tensor::from_array((shape, token_type_ids))?;
            self.session.run(ort::inputs![
                "input_ids" => ids_tensor,
                "attention_mask" => mask_tensor,
                "token_type_ids" => type_tensor,
            ])?
        } else {
            self.session.run(ort::inputs![
                "input_ids" => ids_tensor,
                "attention_mask" => mask_tensor,
            ])?
        };

        let mut selected = None;
        for (name, value) in outputs.iter() {
            if name == "last_hidden_state" {
                selected = Some(value);
            }
        }
        let value = match selected {
            Some(value) => value,
            None => outputs
                .iter()
                .next()
                .map(|(_, value)| value)
                .ok_or_else(|| anyhow!("Model produced no outputs."))?,
        };

        let (shape, data) = value.try_extract_tensor::<f32>()?;
        let dims = shape.as_ref();
        if dims.len() != 3 {
            bail!(
                "Expected a 3-D [batch, sequence, hidden] output, got {} dimensions.",
                dims.len()
            );
        }
        if dims[0] as usize != batch {
            bail!(
                "Model returned {} sequences for a batch of {batch}.",
                dims[0]
            );
        }
        let hidden = dims[2] as usize;
        let seq_len = dims[1] as usize;

        Ok(pool_cls(data, batch, seq_len, hidden))
    }

    pub fn embed(&mut self, texts: &[String], batch_size: usize) -> Result<Vec<Vec<f32>>> {
        let mut all = Vec::with_capacity(texts.len());
        for batch in texts.chunks(batch_size.max(1)) {
            let mut vectors = self.forward(batch)?;
            all.append(&mut vectors);
        }
        Ok(all)
    }
}

pub fn load_chunk_tokenizer(config: &AppConfig) -> Result<Tokenizer> {
    let path = resolve_file(config, TOKENIZER_FILE, true)?;
    Tokenizer::from_file(&path).map_err(|e| anyhow!("Cannot load tokenizer: {e}"))
}

/// Pools the `[CLS]` token — the first of each sequence — from a row-major
/// `[batch, sequence, hidden]` tensor, then L2-normalises it. `bge-m3` is a CLS-pooling
/// model: averaging over the sequence instead produces plausible but wrong vectors.
fn pool_cls(data: &[f32], batch: usize, seq_len: usize, hidden: usize) -> Vec<Vec<f32>> {
    let mut result = Vec::with_capacity(batch);
    for index in 0..batch {
        let start = index * seq_len * hidden;
        let mut vector = Vec::with_capacity(hidden);
        for offset in 0..hidden {
            vector.push(data[start + offset]);
        }
        normalize_l2(&mut vector);
        result.push(vector);
    }
    result
}

pub fn normalize_l2(vector: &mut [f32]) {
    let mut sum = 0.0_f32;
    for value in vector.iter() {
        sum += value * value;
    }
    let norm = sum.sqrt();
    if norm <= f32::EPSILON {
        return;
    }
    for value in vector.iter_mut() {
        *value /= norm;
    }
}

#[derive(Serialize)]
struct ModelReport {
    model_name: String,
    onnx_file: String,
    cache_dir: String,
    execution_provider: String,
    tokenizer_cached: bool,
    model_cached: bool,
}

fn model_report(config: &AppConfig) -> ModelReport {
    ModelReport {
        model_name: config.model.name.0.clone(),
        onnx_file: config.model.onnx_file.clone(),
        cache_dir: config.model.cache_dir.display().to_string(),
        execution_provider: config.model.execution_provider.as_str().to_string(),
        tokenizer_cached: cached_file(config, TOKENIZER_FILE).is_some(),
        model_cached: cached_file(config, &config.model.onnx_file).is_some(),
    }
}

pub fn cmd_models_show(config: &AppConfig, format: Format) -> Result<ExitCode> {
    let report = model_report(config);
    match format {
        Format::Json => output::print_json(&report)?,
        Format::Human => {
            let mut table = Table::new();
            table.load_style(presets::UTF8_FULL);
            table.set_header(vec!["configured model", ""]);
            table.add_row(vec!["name", &report.model_name]);
            table.add_row(vec!["onnx file", &report.onnx_file]);
            table.add_row(vec!["cache dir", &report.cache_dir]);
            table.add_row(vec!["execution provider", &report.execution_provider]);
            table.add_row(vec![
                "tokenizer cached",
                &report.tokenizer_cached.to_string(),
            ]);
            table.add_row(vec!["model cached", &report.model_cached.to_string()]);
            output::print_line(&table.to_string());
        }
    }
    Ok(ExitCode::SUCCESS)
}

#[derive(Serialize)]
struct ValidationReport {
    model_name: String,
    cache_dir: String,
    offline_only: bool,
    ok: bool,
    detail: String,
}

pub fn cmd_models_validate(
    config: &AppConfig,
    offline_only: bool,
    format: Format,
) -> Result<ExitCode> {
    let mut detail = String::from("model and tokenizer are available");
    let mut ok = true;

    for file in [TOKENIZER_FILE, config.model.onnx_file.as_str()] {
        if let Err(e) = resolve_file(config, file, offline_only) {
            ok = false;
            detail = e.to_string();
            break;
        }
    }

    let report = ValidationReport {
        model_name: config.model.name.0.clone(),
        cache_dir: config.model.cache_dir.display().to_string(),
        offline_only,
        ok,
        detail: detail.clone(),
    };

    match format {
        Format::Json => output::print_json(&report)?,
        Format::Human => {
            if ok {
                output::print_success(&detail);
            } else {
                output::print_warning(&detail);
            }
        }
    }

    if ok {
        Ok(ExitCode::SUCCESS)
    } else {
        Ok(ExitCode::from(crate::cli::EXIT_VALIDATION_FAILED))
    }
}

pub fn cmd_models_bootstrap(config: &AppConfig, format: Format) -> Result<ExitCode> {
    let mut detail = String::from("model and tokenizer downloaded");
    let mut ok = true;

    if let Format::Human = format {
        output::print_line(&format!(
            "Downloading '{}' into {}",
            config.model.name.0,
            hub_dir(config).display()
        ));
    }

    for file in [TOKENIZER_FILE, config.model.onnx_file.as_str()] {
        if let Err(e) = resolve_file(config, file, false) {
            ok = false;
            detail = e.to_string();
            break;
        }
    }

    let report = ValidationReport {
        model_name: config.model.name.0.clone(),
        cache_dir: config.model.cache_dir.display().to_string(),
        offline_only: false,
        ok,
        detail: detail.clone(),
    };

    match format {
        Format::Json => output::print_json(&report)?,
        Format::Human => {
            if ok {
                output::print_success(&detail);
            } else {
                output::print_warning(&detail);
            }
        }
    }

    if ok {
        Ok(ExitCode::SUCCESS)
    } else {
        Ok(ExitCode::from(crate::cli::EXIT_VALIDATION_FAILED))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pooling_takes_the_cls_token_not_the_mean() {
        let batch = 2;
        let seq_len = 4;
        let hidden = 2;
        let mut data = Vec::new();
        for _ in 0..batch {
            data.extend_from_slice(&[1.0, 0.0]);
            for _ in 1..seq_len {
                data.extend_from_slice(&[0.0, 1.0]);
            }
        }

        let pooled = pool_cls(&data, batch, seq_len, hidden);

        assert_eq!(pooled.len(), batch);
        for vector in &pooled {
            assert!(
                (vector[0] - 1.0).abs() < 1e-6 && vector[1].abs() < 1e-6,
                "expected the CLS token [1,0], got {vector:?} — mean pooling would give ~[0.32,0.95]"
            );
        }
    }

    #[test]
    fn pooling_addresses_each_sequence_independently() {
        let hidden = 2;
        let seq_len = 3;
        let data = vec![5.0, 0.0, 9.9, 9.9, 9.9, 9.9, 0.0, 7.0, 9.9, 9.9, 9.9, 9.9];

        let pooled = pool_cls(&data, 2, seq_len, hidden);

        assert!((pooled[0][0] - 1.0).abs() < 1e-6, "first sequence CLS");
        assert!((pooled[1][1] - 1.0).abs() < 1e-6, "second sequence CLS");
    }

    #[test]
    fn normalize_makes_unit_length() {
        let mut vector = vec![3.0_f32, 4.0];
        normalize_l2(&mut vector);
        assert!((vector[0] - 0.6).abs() < 1e-6);
        assert!((vector[1] - 0.8).abs() < 1e-6);
    }

    #[test]
    fn normalize_leaves_zero_vector_untouched() {
        let mut vector = vec![0.0_f32, 0.0];
        normalize_l2(&mut vector);
        assert_eq!(vector, vec![0.0, 0.0]);
    }

    #[test]
    fn normalized_vector_has_norm_one() {
        let mut vector = vec![1.0_f32, 2.0, 3.0, 4.0];
        normalize_l2(&mut vector);
        let mut sum = 0.0_f32;
        for value in &vector {
            sum += value * value;
        }
        assert!((sum.sqrt() - 1.0).abs() < 1e-6);
    }

    fn cosine(a: &[f32], b: &[f32]) -> f32 {
        let mut dot = 0.0_f32;
        let mut norm_a = 0.0_f32;
        let mut norm_b = 0.0_f32;
        for index in 0..a.len() {
            dot += a[index] * b[index];
            norm_a += a[index] * a[index];
            norm_b += b[index] * b[index];
        }
        dot / (norm_a.sqrt() * norm_b.sqrt())
    }

    /// Requires a downloaded model. Run with:
    /// `VECSTASH_PARITY_CONFIG=<config.toml> VECSTASH_PARITY_REFERENCE=<reference.json>
    ///  cargo test parity -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn embeddings_match_the_python_reference() {
        let Ok(config_path) = std::env::var("VECSTASH_PARITY_CONFIG") else {
            panic!("VECSTASH_PARITY_CONFIG is required for the parity test");
        };
        let Ok(reference_path) = std::env::var("VECSTASH_PARITY_REFERENCE") else {
            panic!("VECSTASH_PARITY_REFERENCE is required for the parity test");
        };

        let config = crate::config::load(Some(std::path::Path::new(&config_path)))
            .expect("config must load");
        let reference: serde_json::Value = serde_json::from_str(
            &std::fs::read_to_string(&reference_path).expect("reference must be readable"),
        )
        .expect("reference must be valid JSON");

        let mut texts: Vec<String> = Vec::new();
        for value in reference["texts"].as_array().expect("texts array") {
            texts.push(value.as_str().expect("text is a string").to_string());
        }

        let mut expected: Vec<Vec<f32>> = Vec::new();
        for row in reference["vectors"].as_array().expect("vectors array") {
            let mut vector: Vec<f32> = Vec::new();
            for value in row.as_array().expect("vector is an array") {
                vector.push(value.as_f64().expect("number") as f32);
            }
            expected.push(vector);
        }

        let mut embedder = Embedder::load(&config).expect("embedder must load");
        let actual = embedder.embed(&texts, 8).expect("embedding must succeed");

        assert_eq!(actual.len(), expected.len());
        let mut worst = 1.0_f32;
        for index in 0..actual.len() {
            assert_eq!(
                actual[index].len(),
                expected[index].len(),
                "dimension mismatch for text {index}"
            );
            let similarity = cosine(&actual[index], &expected[index]);
            println!(
                "text {index}: cosine = {similarity:.6}  |  {}",
                texts[index]
            );
            if similarity < worst {
                worst = similarity;
            }
        }
        println!("worst cosine similarity: {worst:.6}");
        assert!(
            worst > 0.999,
            "worst cosine similarity {worst:.6} is below the 0.999 parity threshold"
        );
    }
}
