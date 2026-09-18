use crate::extract::ExtractedDocument;
use anyhow::Result;
use sha2::{Digest, Sha256};
use text_splitter::{ChunkConfig, TextSplitter};
use tokenizers::Tokenizer;

#[derive(Debug, Clone, PartialEq)]
pub struct Chunk {
    pub chunk_id: String,
    pub document_id: String,
    pub text: String,
    pub chunk_index: usize,
}

fn chunk_id(document_id: &str, index: usize) -> String {
    let mut hasher = Sha256::new();
    hasher.update(format!("{document_id}:{index}").as_bytes());
    hex::encode(hasher.finalize())
}

fn assemble(document_id: &str, pieces: Vec<&str>) -> Vec<Chunk> {
    let mut chunks = Vec::with_capacity(pieces.len());
    for (index, piece) in pieces.into_iter().enumerate() {
        let piece = piece.trim();
        if piece.is_empty() {
            continue;
        }
        chunks.push(Chunk {
            chunk_id: chunk_id(document_id, index),
            document_id: document_id.to_string(),
            text: piece.to_string(),
            chunk_index: index,
        });
    }
    chunks
}

pub fn chunk_with_tokenizer(
    doc: &ExtractedDocument,
    tokenizer: Tokenizer,
    chunk_tokens: usize,
    chunk_overlap: usize,
) -> Result<Vec<Chunk>> {
    let config = ChunkConfig::new(chunk_tokens)
        .with_sizer(tokenizer)
        .with_overlap(chunk_overlap)?;
    let splitter = TextSplitter::new(config);
    let pieces: Vec<&str> = splitter.chunks(&doc.text).collect();
    Ok(assemble(&doc.document_id, pieces))
}

#[cfg(test)]
pub fn chunk_with_chars(
    doc: &ExtractedDocument,
    chunk_chars: usize,
    chunk_overlap: usize,
) -> Result<Vec<Chunk>> {
    let config = ChunkConfig::new(chunk_chars).with_overlap(chunk_overlap)?;
    let splitter = TextSplitter::new(config);
    let pieces: Vec<&str> = splitter.chunks(&doc.text).collect();
    Ok(assemble(&doc.document_id, pieces))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn document(text: &str) -> ExtractedDocument {
        ExtractedDocument {
            document_id: "doc-1".to_string(),
            source_path: "/tmp/x.txt".to_string(),
            source_kind: "txt".to_string(),
            content_hash: "hash".to_string(),
            byte_size: text.len() as u64,
            char_count: text.chars().count(),
            line_count: 1,
            text: text.to_string(),
        }
    }

    #[test]
    fn long_text_splits_into_multiple_chunks() {
        let text = "word ".repeat(400);
        let chunks = chunk_with_chars(&document(&text), 300, 50).expect("chunk");
        assert!(chunks.len() > 1);
        for chunk in &chunks {
            assert!(chunk.text.chars().count() <= 300);
        }
    }

    #[test]
    fn short_text_stays_one_chunk() {
        let chunks = chunk_with_chars(&document("a short paragraph"), 300, 50).expect("chunk");
        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].text, "a short paragraph");
    }

    #[test]
    fn empty_text_yields_no_chunks() {
        let chunks = chunk_with_chars(&document(""), 300, 50).expect("chunk");
        assert!(chunks.is_empty());
    }

    #[test]
    fn whitespace_only_text_yields_no_chunks() {
        let chunks = chunk_with_chars(&document("   \n\n  "), 300, 50).expect("chunk");
        assert!(chunks.is_empty());
    }

    #[test]
    fn chunk_indexes_are_sequential() {
        let text = "word ".repeat(400);
        let chunks = chunk_with_chars(&document(&text), 300, 0).expect("chunk");
        for (position, chunk) in chunks.iter().enumerate() {
            assert_eq!(chunk.chunk_index, position);
        }
    }

    #[test]
    fn chunk_ids_are_unique() {
        let text = "word ".repeat(400);
        let chunks = chunk_with_chars(&document(&text), 300, 0).expect("chunk");
        let mut seen = std::collections::HashSet::new();
        for chunk in &chunks {
            assert!(seen.insert(chunk.chunk_id.clone()), "duplicate chunk_id");
        }
    }

    #[test]
    fn chunk_id_is_deterministic() {
        let text = "word ".repeat(400);
        let first = chunk_with_chars(&document(&text), 300, 0).expect("chunk");
        let second = chunk_with_chars(&document(&text), 300, 0).expect("chunk");
        assert_eq!(first, second);
    }

    #[test]
    fn chunks_inherit_document_id() {
        let text = "word ".repeat(400);
        let chunks = chunk_with_chars(&document(&text), 300, 0).expect("chunk");
        for chunk in &chunks {
            assert_eq!(chunk.document_id, "doc-1");
        }
    }

    #[test]
    fn overlap_not_smaller_than_capacity_is_rejected() {
        let result = chunk_with_chars(&document("text"), 100, 100);
        assert!(result.is_err(), "overlap >= capacity must be rejected");
    }
}
