"""Ingestion: raw HTML -> cleaned blocks -> chunks -> vectors -> indexes."""

from .bootstrap import IndexStatus, ensure_index, probe_index
from .chunker import chunk_page, is_return_heavy, split_sentences, summarise
from .clean import Block, ParsedPage, check_not_empty, parse_file, parse_page
from .embedder import DEFAULT_MODEL, Embedder
from .pipeline import IngestReport, run_ingest

__all__ = [
    "Block",
    "DEFAULT_MODEL",
    "Embedder",
    "IngestReport",
    "IndexStatus",
    "ParsedPage",
    "check_not_empty",
    "chunk_page",
    "ensure_index",
    "is_return_heavy",
    "parse_file",
    "parse_page",
    "probe_index",
    "run_ingest",
    "split_sentences",
    "summarise",
]
