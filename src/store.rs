use crate::config::AppConfig;
use crate::extract::ExtractedDocument;
use crate::output::{self, Format};
use anyhow::{Context, Result, bail};
use comfy_table::{Table, presets};
use rusqlite::{Connection, OptionalExtension, params};
use serde::Serialize;
use std::fs;
use std::path::Path;
use std::process::ExitCode;

pub const SCHEMA_VERSION: i64 = 1;
const META_VECTOR_DIM: &str = "vector_dim";

#[derive(Debug, Clone, PartialEq)]
pub struct SearchHit {
    pub score: f32,
    pub document_id: String,
    pub source_path: String,
    pub chunk_text: String,
    pub chunk_index: i64,
}

#[derive(Debug, Clone, Copy, Serialize)]
pub struct StoreStatus {
    pub schema_version: i64,
    pub vector_dim: Option<i64>,
    pub documents_count: i64,
    pub chunks_count: i64,
}

pub struct Store {
    conn: Connection,
}

impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("Cannot create {}", parent.display()))?;
        }
        let conn = Connection::open(path)
            .with_context(|| format!("Cannot open database {}", path.display()))?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;

        let store = Store { conn };
        store.migrate()?;
        Ok(store)
    }

    fn migrate(&self) -> Result<()> {
        self.conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                char_count INTEGER NOT NULL,
                line_count INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
            CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash);",
        )?;
        self.conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?1)",
            params![SCHEMA_VERSION],
        )?;
        Ok(())
    }

    pub fn schema_version(&self) -> Result<i64> {
        let version = self.conn.query_row(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations",
            [],
            |row| row.get(0),
        )?;
        Ok(version)
    }

    pub fn vector_dim(&self) -> Result<Option<i64>> {
        let raw: Option<String> = self
            .conn
            .query_row(
                "SELECT value FROM index_meta WHERE key = ?1",
                params![META_VECTOR_DIM],
                |row| row.get(0),
            )
            .optional()?;
        let Some(raw) = raw else {
            return Ok(None);
        };
        Ok(Some(raw.parse()?))
    }

    pub fn ensure_dimension(&self, dim: usize) -> Result<()> {
        let dim = dim as i64;
        let Some(existing) = self.vector_dim()? else {
            self.conn.execute(
                "INSERT OR REPLACE INTO index_meta(key, value) VALUES (?1, ?2)",
                params![META_VECTOR_DIM, dim.to_string()],
            )?;
            return Ok(());
        };
        if existing != dim {
            bail!(
                "Vector dimension mismatch: index has {existing}-dim vectors but current model \
                 produces {dim}-dim. Run 'vecstash reset' to clear the index before switching models."
            );
        }
        Ok(())
    }

    pub fn documents_count(&self) -> Result<i64> {
        let count = self
            .conn
            .query_row("SELECT COUNT(*) FROM documents", [], |row| row.get(0))?;
        Ok(count)
    }

    pub fn chunks_count(&self) -> Result<i64> {
        let count = self
            .conn
            .query_row("SELECT COUNT(*) FROM chunks", [], |row| row.get(0))?;
        Ok(count)
    }

    pub fn status(&self) -> Result<StoreStatus> {
        Ok(StoreStatus {
            schema_version: self.schema_version()?,
            vector_dim: self.vector_dim()?,
            documents_count: self.documents_count()?,
            chunks_count: self.chunks_count()?,
        })
    }

    pub fn upsert_document(&self, doc: &ExtractedDocument) -> Result<()> {
        let ExtractedDocument {
            document_id,
            source_path,
            source_kind,
            content_hash,
            byte_size,
            char_count,
            line_count,
            text: _,
        } = doc;

        let metadata = serde_json::json!({
            "file_name": file_name(source_path),
            "file_suffix": file_suffix(source_path),
            "byte_size": byte_size,
            "char_count": char_count,
            "line_count": line_count,
            "content_hash": content_hash,
        });

        self.conn.execute(
            "INSERT INTO documents(
                document_id, source_path, source_kind, content_hash,
                byte_size, char_count, line_count, metadata_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
             ON CONFLICT(document_id) DO UPDATE SET
                source_path = excluded.source_path,
                source_kind = excluded.source_kind,
                content_hash = excluded.content_hash,
                byte_size = excluded.byte_size,
                char_count = excluded.char_count,
                line_count = excluded.line_count,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP",
            params![
                document_id,
                source_path,
                source_kind,
                content_hash,
                *byte_size as i64,
                *char_count as i64,
                *line_count as i64,
                metadata.to_string(),
            ],
        )?;
        Ok(())
    }

    pub fn replace_chunks(
        &mut self,
        document_id: &str,
        chunks: &[crate::chunk::Chunk],
        embeddings: &[Vec<f32>],
    ) -> Result<()> {
        if chunks.len() != embeddings.len() {
            bail!(
                "Mismatch: {} chunks but {} embeddings",
                chunks.len(),
                embeddings.len()
            );
        }

        let tx = self.conn.transaction()?;
        tx.execute(
            "DELETE FROM chunks WHERE document_id = ?1",
            params![document_id],
        )?;
        {
            let mut stmt = tx.prepare(
                "INSERT INTO chunks(chunk_id, document_id, chunk_index, text, embedding)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
            )?;
            for (index, chunk) in chunks.iter().enumerate() {
                let crate::chunk::Chunk {
                    chunk_id,
                    document_id: chunk_document_id,
                    text,
                    chunk_index,
                } = chunk;
                stmt.execute(params![
                    chunk_id,
                    chunk_document_id,
                    *chunk_index as i64,
                    text,
                    encode_vector(&embeddings[index]),
                ])?;
            }
        }
        tx.commit()?;
        Ok(())
    }

    pub fn search(&self, query: &[f32], top_k: usize) -> Result<Vec<SearchHit>> {
        let mut stmt = self.conn.prepare(
            "SELECT c.document_id, d.source_path, c.chunk_text_alias, c.chunk_index, c.embedding
             FROM (SELECT document_id, text AS chunk_text_alias, chunk_index, embedding FROM chunks) c
             JOIN documents d ON d.document_id = c.document_id",
        )?;

        let mut hits: Vec<SearchHit> = Vec::new();
        let mut rows = stmt.query([])?;
        while let Some(row) = rows.next()? {
            let document_id: String = row.get(0)?;
            let source_path: String = row.get(1)?;
            let chunk_text: String = row.get(2)?;
            let chunk_index: i64 = row.get(3)?;
            let blob: Vec<u8> = row.get(4)?;
            let vector = decode_vector(&blob)?;
            if vector.len() != query.len() {
                bail!(
                    "Vector dimension mismatch: index has {}-dim vectors but query is {}-dim. \
                     Run 'vecstash reset' to clear the index before switching models.",
                    vector.len(),
                    query.len()
                );
            }
            hits.push(SearchHit {
                score: dot(query, &vector),
                document_id,
                source_path,
                chunk_text,
                chunk_index,
            });
        }

        hits.sort_by(|a, b| b.score.total_cmp(&a.score));
        hits.truncate(top_k);
        Ok(hits)
    }
}

fn file_name(path: &str) -> String {
    Path::new(path)
        .file_name()
        .map(|v| v.to_string_lossy().into_owned())
        .unwrap_or_default()
}

fn file_suffix(path: &str) -> String {
    Path::new(path)
        .extension()
        .map(|v| format!(".{}", v.to_string_lossy().to_lowercase()))
        .unwrap_or_default()
}

pub fn encode_vector(vector: &[f32]) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(vector.len() * 4);
    for value in vector {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

pub fn decode_vector(bytes: &[u8]) -> Result<Vec<f32>> {
    if !bytes.len().is_multiple_of(4) {
        bail!(
            "Corrupt embedding blob: {} bytes is not a multiple of 4",
            bytes.len()
        );
    }
    let mut vector = Vec::with_capacity(bytes.len() / 4);
    for offset in (0..bytes.len()).step_by(4) {
        let chunk = [
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
        ];
        vector.push(f32::from_le_bytes(chunk));
    }
    Ok(vector)
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    let mut sum = 0.0;
    for index in 0..a.len() {
        sum += a[index] * b[index];
    }
    sum
}

#[derive(Serialize)]
struct StatusReport<'a> {
    app_name: &'a str,
    model_name: &'a str,
    model_onnx_file: &'a str,
    model_cache_dir: String,
    execution_provider: &'a str,
    data_dir: String,
    sqlite_path: String,
    log_path: String,
    max_batch_size: usize,
    chunk_tokens: usize,
    chunk_overlap: usize,
    schema_version: i64,
    vector_dim: Option<i64>,
    documents_count: i64,
    chunks_count: i64,
}

pub fn cmd_status(config: &AppConfig, format: Format) -> Result<ExitCode> {
    let store = Store::open(&config.paths.sqlite_path)?;
    let StoreStatus {
        schema_version,
        vector_dim,
        documents_count,
        chunks_count,
    } = store.status()?;

    let report = StatusReport {
        app_name: &config.app.name.0,
        model_name: &config.model.name.0,
        model_onnx_file: &config.model.onnx_file,
        model_cache_dir: config.model.cache_dir.display().to_string(),
        execution_provider: config.model.execution_provider.as_str(),
        data_dir: config.paths.data_dir.display().to_string(),
        sqlite_path: config.paths.sqlite_path.display().to_string(),
        log_path: config.paths.log_path.display().to_string(),
        max_batch_size: config.runtime.max_batch_size,
        chunk_tokens: config.runtime.chunk_tokens,
        chunk_overlap: config.runtime.chunk_overlap,
        schema_version,
        vector_dim,
        documents_count,
        chunks_count,
    };

    match format {
        Format::Json => output::print_json(&report)?,
        Format::Human => {
            let mut table = Table::new();
            table.load_style(presets::UTF8_FULL);
            table.set_header(vec!["vecstash status", ""]);
            table.add_row(vec!["app", report.app_name]);
            table.add_row(vec!["model", report.model_name]);
            table.add_row(vec!["onnx file", report.model_onnx_file]);
            table.add_row(vec!["execution provider", report.execution_provider]);
            table.add_row(vec!["data dir", &report.data_dir]);
            table.add_row(vec!["sqlite", &report.sqlite_path]);
            table.add_row(vec!["log", &report.log_path]);
            table.add_row(vec!["schema version", &schema_version.to_string()]);
            table.add_row(vec![
                "vector dim",
                &vector_dim
                    .map(|v| v.to_string())
                    .unwrap_or_else(|| "-".into()),
            ]);
            table.add_row(vec!["documents", &documents_count.to_string()]);
            table.add_row(vec!["chunks", &chunks_count.to_string()]);
            output::print_line(&table.to_string());
        }
    }
    Ok(ExitCode::SUCCESS)
}

#[derive(Serialize)]
struct StorageReport {
    sqlite_path: String,
    sqlite_bytes: u64,
    total_bytes: u64,
}

pub fn cmd_storage(config: &AppConfig, format: Format) -> Result<ExitCode> {
    let sqlite_bytes = file_size(&config.paths.sqlite_path);
    let mut total_bytes = sqlite_bytes;
    for suffix in ["-wal", "-shm"] {
        let mut sidecar = config.paths.sqlite_path.clone().into_os_string();
        sidecar.push(suffix);
        total_bytes += file_size(Path::new(&sidecar));
    }

    let report = StorageReport {
        sqlite_path: config.paths.sqlite_path.display().to_string(),
        sqlite_bytes,
        total_bytes,
    };

    match format {
        Format::Json => output::print_json(&report)?,
        Format::Human => {
            let mut table = Table::new();
            table.load_style(presets::UTF8_FULL);
            table.set_header(vec!["vecstash storage", ""]);
            table.add_row(vec!["sqlite", &report.sqlite_path]);
            table.add_row(vec!["sqlite bytes", &report.sqlite_bytes.to_string()]);
            table.add_row(vec!["total bytes", &report.total_bytes.to_string()]);
            output::print_line(&table.to_string());
        }
    }
    Ok(ExitCode::SUCCESS)
}

fn file_size(path: &Path) -> u64 {
    match fs::metadata(path) {
        Ok(meta) => meta.len(),
        Err(_) => 0,
    }
}

pub fn cmd_reset(config: &AppConfig, force: bool, format: Format) -> Result<ExitCode> {
    let mut targets: Vec<std::path::PathBuf> = Vec::new();
    if config.paths.sqlite_path.exists() {
        targets.push(config.paths.sqlite_path.clone());
    }
    for suffix in ["-wal", "-shm"] {
        let mut sidecar = config.paths.sqlite_path.clone().into_os_string();
        sidecar.push(suffix);
        let sidecar = std::path::PathBuf::from(sidecar);
        if sidecar.exists() {
            targets.push(sidecar);
        }
    }

    if targets.is_empty() {
        match format {
            Format::Json => {
                output::print_json(&serde_json::json!({ "status": "nothing_to_reset" }))?
            }
            Format::Human => output::print_warning("Nothing to reset."),
        }
        return Ok(ExitCode::SUCCESS);
    }

    if !force {
        output::print_line("The following will be deleted:");
        for target in &targets {
            output::print_line(&format!("  {}", target.display()));
        }
        output::print_line("Re-run with --force to confirm.");
        return Ok(ExitCode::from(1));
    }

    let mut deleted: Vec<String> = Vec::new();
    for target in &targets {
        fs::remove_file(target).with_context(|| format!("Cannot delete {}", target.display()))?;
        deleted.push(target.display().to_string());
    }

    match format {
        Format::Json => output::print_json(&serde_json::json!({
            "status": "reset_complete",
            "deleted": deleted,
        }))?,
        Format::Human => output::print_success(&format!(
            "Reset complete. {} file(s) deleted.",
            deleted.len()
        )),
    }
    Ok(ExitCode::SUCCESS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chunk::Chunk;

    fn sample_document(id: &str) -> ExtractedDocument {
        ExtractedDocument {
            document_id: id.to_string(),
            source_path: "/tmp/sample.md".to_string(),
            source_kind: "md".to_string(),
            content_hash: "deadbeef".to_string(),
            byte_size: 10,
            char_count: 10,
            line_count: 1,
            text: "hello".to_string(),
        }
    }

    fn sample_chunk(document_id: &str, index: usize) -> Chunk {
        Chunk {
            chunk_id: format!("{document_id}-{index}"),
            document_id: document_id.to_string(),
            text: format!("chunk {index}"),
            chunk_index: index,
        }
    }

    fn open_temp_store() -> (tempfile::TempDir, Store) {
        let dir = tempfile::tempdir().expect("tempdir");
        let store = Store::open(&dir.path().join("metadata.db")).expect("store opens");
        (dir, store)
    }

    #[test]
    fn fresh_store_reports_empty_status() {
        let (_dir, store) = open_temp_store();
        let status = store.status().expect("status");
        assert_eq!(status.schema_version, SCHEMA_VERSION);
        assert_eq!(status.documents_count, 0);
        assert_eq!(status.chunks_count, 0);
        assert_eq!(status.vector_dim, None);
    }

    #[test]
    fn document_roundtrips() {
        let (_dir, store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");
        assert_eq!(store.documents_count().expect("count"), 1);

        store
            .upsert_document(&sample_document("doc-1"))
            .expect("re-upsert");
        assert_eq!(store.documents_count().expect("count"), 1);
    }

    #[test]
    fn chunks_are_replaced_not_accumulated() {
        let (_dir, mut store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");

        let chunks = vec![sample_chunk("doc-1", 0)];
        store
            .replace_chunks("doc-1", &chunks, &[vec![1.0, 0.0]])
            .expect("first insert");
        assert_eq!(store.chunks_count().expect("count"), 1);

        let chunks = vec![sample_chunk("doc-1", 0), sample_chunk("doc-1", 1)];
        store
            .replace_chunks("doc-1", &chunks, &[vec![1.0, 0.0], vec![0.0, 1.0]])
            .expect("second insert");
        assert_eq!(store.chunks_count().expect("count"), 2);
    }

    #[test]
    fn mismatched_chunk_and_embedding_counts_are_rejected() {
        let (_dir, mut store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");
        let err = store
            .replace_chunks("doc-1", &[sample_chunk("doc-1", 0)], &[])
            .expect_err("must reject");
        assert!(err.to_string().contains("1 chunks but 0 embeddings"));
    }

    #[test]
    fn search_ranks_by_cosine_similarity() {
        let (_dir, mut store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");
        let chunks = vec![sample_chunk("doc-1", 0), sample_chunk("doc-1", 1)];
        store
            .replace_chunks("doc-1", &chunks, &[vec![1.0, 0.0], vec![0.0, 1.0]])
            .expect("insert");

        let hits = store.search(&[1.0, 0.0], 5).expect("search");
        assert_eq!(hits.len(), 2);
        assert_eq!(hits[0].chunk_index, 0);
        assert!(hits[0].score > hits[1].score);
    }

    #[test]
    fn search_respects_top_k() {
        let (_dir, mut store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");
        let chunks = vec![sample_chunk("doc-1", 0), sample_chunk("doc-1", 1)];
        store
            .replace_chunks("doc-1", &chunks, &[vec![1.0, 0.0], vec![0.0, 1.0]])
            .expect("insert");

        let hits = store.search(&[1.0, 0.0], 1).expect("search");
        assert_eq!(hits.len(), 1);
    }

    #[test]
    fn deleting_document_cascades_to_chunks() {
        let (_dir, mut store) = open_temp_store();
        store
            .upsert_document(&sample_document("doc-1"))
            .expect("upsert");
        store
            .replace_chunks("doc-1", &[sample_chunk("doc-1", 0)], &[vec![1.0, 0.0]])
            .expect("insert");

        store
            .conn
            .execute("DELETE FROM documents WHERE document_id = 'doc-1'", [])
            .expect("delete");
        assert_eq!(store.chunks_count().expect("count"), 0);
    }

    #[test]
    fn dimension_is_recorded_on_first_use() {
        let (_dir, store) = open_temp_store();
        store.ensure_dimension(1024).expect("first dimension");
        assert_eq!(store.vector_dim().expect("dim"), Some(1024));
    }

    #[test]
    fn changing_dimension_is_rejected() {
        let (_dir, store) = open_temp_store();
        store.ensure_dimension(1024).expect("first dimension");
        let err = store.ensure_dimension(768).expect_err("must reject");
        assert!(err.to_string().contains("dimension mismatch"));
        assert!(err.to_string().contains("vecstash reset"));
    }

    #[test]
    fn vector_blob_roundtrips() {
        let vector = vec![1.5_f32, -2.25, 0.0, 7.125];
        let decoded = decode_vector(&encode_vector(&vector)).expect("decode");
        assert_eq!(decoded, vector);
    }

    #[test]
    fn corrupt_blob_is_rejected() {
        let err = decode_vector(&[0, 1, 2]).expect_err("must reject");
        assert!(err.to_string().contains("not a multiple of 4"));
    }
}
