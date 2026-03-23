from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from vecstash.config import AppConfig
from vecstash.extraction import ExtractedDocument

SCHEMA_VERSION = 1
DEFAULT_COLLECTION_NAME = "document_chunks"


@dataclass(frozen=True)
class StorageStatus:
    schema_version: int
    collection_name: str
    points_count: int
    documents_count: int


class SQLiteRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def migrate(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                """
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
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunk_index_state (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    point_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                )
                """
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
                (SCHEMA_VERSION,),
            )

    def get_schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        if row is None:
            return 0
        return int(row["version"])

    def upsert_document(self, doc: ExtractedDocument) -> None:
        metadata_json = json.dumps(doc.metadata, sort_keys=True)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO documents(
                    document_id, source_path, source_kind, content_hash, byte_size, char_count, line_count, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    source_kind=excluded.source_kind,
                    content_hash=excluded.content_hash,
                    byte_size=excluded.byte_size,
                    char_count=excluded.char_count,
                    line_count=excluded.line_count,
                    metadata_json=excluded.metadata_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    doc.document_id,
                    str(doc.source_path),
                    doc.source_kind,
                    str(doc.metadata["content_hash"]),
                    int(doc.metadata["byte_size"]),
                    int(doc.metadata["char_count"]),
                    int(doc.metadata["line_count"]),
                    metadata_json,
                ),
            )

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE document_id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        payload["metadata_json"] = json.loads(payload["metadata_json"])
        return payload

    def documents_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
        return int(row["n"]) if row else 0


class QdrantRepository:
    def __init__(self, qdrant_path: Path, collection_name: str = DEFAULT_COLLECTION_NAME):
        self.qdrant_path = qdrant_path
        self.qdrant_path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.client = QdrantClient(path=str(qdrant_path))

    def ensure_collection(self, vector_size: int = 768, distance: qmodels.Distance = qmodels.Distance.COSINE) -> None:
        collections = self.client.get_collections().collections
        exists = any(col.name == self.collection_name for col in collections)
        if exists:
            return
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
            hnsw_config=qmodels.HnswConfigDiff(m=16, ef_construct=100),
        )

    def get_collection_points_count(self) -> int:
        info = self.client.get_collection(self.collection_name)
        return int(info.points_count or 0)


class StorageManager:
    def __init__(self, config: AppConfig, collection_name: str = DEFAULT_COLLECTION_NAME):
        self.config = config
        self.sqlite = SQLiteRepository(config.paths.sqlite_path)
        self.qdrant = QdrantRepository(config.paths.qdrant_path, collection_name=collection_name)
        self.collection_name = collection_name

    def close(self) -> None:
        self.sqlite.close()
        self.qdrant.client.close()

    def initialize(self, vector_size: int = 768) -> StorageStatus:
        self.sqlite.migrate()
        self.qdrant.ensure_collection(vector_size=vector_size)
        return self.status()

    def status(self) -> StorageStatus:
        return StorageStatus(
            schema_version=self.sqlite.get_schema_version(),
            collection_name=self.collection_name,
            points_count=self.qdrant.get_collection_points_count(),
            documents_count=self.sqlite.documents_count(),
        )

    def upsert_document_metadata(self, doc: ExtractedDocument) -> None:
        self.sqlite.upsert_document(doc)

    def get_document_metadata(self, document_id: str) -> dict[str, Any] | None:
        return self.sqlite.get_document(document_id)
