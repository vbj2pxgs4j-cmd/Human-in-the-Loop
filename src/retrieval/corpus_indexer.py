"""Hybrid Corpus Indexer combining BM25 lexical search and Dense Vector embeddings."""

import json
import logging
import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
from rank_bm25 import BM25Okapi

from src.config import Settings, get_settings
from src.models.corpus import CorpusChunk, CorpusDocument, SearchResult

logger = logging.getLogger(__name__)

# Stopwords excluded from BM25 lexical tokenization to prevent frequency distortion
DEFAULT_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have",
    "having", "he", "her", "here", "hers", "herself", "him", "himself", "his",
    "how", "i", "if", "in", "into", "is", "it", "its", "itself", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
    "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own",
    "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was", "we",
    "were", "what", "when", "where", "which", "while", "who", "whom", "why", "with",
    "would", "you", "your", "yours", "yourself", "yourselves"
}


def simple_tokenize(text: str, stopwords: Optional[Set[str]] = None) -> List[str]:
    """Alphanumeric tokenizer with stopword pruning for precision lexical matching."""
    stops = stopwords if stopwords is not None else DEFAULT_STOPWORDS
    tokens = re.findall(r"\b[A-Za-z0-9_]+\b", text.lower())
    return [t for t in tokens if t not in stops]


class CorpusIndexer:
    """Manages document chunking, BM25 lexical indexing, and dense vector embeddings."""

    def __init__(
        self,
        embedding_model_name: Optional[str] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.embedding_model_name = (
            embedding_model_name or self.settings.EMBEDDING_MODEL_NAME
        )
        self.documents: Dict[str, CorpusDocument] = {}
        self.chunks: List[CorpusChunk] = []
        self.tokenized_corpus: List[List[str]] = []
        self.bm25: Optional[BM25Okapi] = None
        self.chunk_embeddings: Optional[np.ndarray] = None
        self._model: Any = None

    @property
    def model(self) -> Any:
        """Lazy loader for SentenceTransformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s", self.embedding_model_name)
            self._model = SentenceTransformer(self.embedding_model_name)
        return self._model

    def chunk_document(
        self,
        doc: CorpusDocument,
        chunk_size: int = 300,
        overlap: int = 50,
    ) -> List[CorpusChunk]:
        """Split a document into semantic passages (250-400 words) with overlap.

        Each chunk preserves document title and category for high semantic resolution.
        """
        paragraphs = [p.strip() for p in doc.content.split("\n\n") if p.strip()]
        chunks_text: List[str] = []

        for para in paragraphs:
            para_words = para.split()
            if not para_words:
                continue

            # If paragraph fits comfortably within chunk_size, treat as dedicated chunk
            if len(para_words) <= chunk_size:
                chunk_body = f"[{doc.category}] {doc.title}: {para}"
                chunks_text.append(chunk_body)
            else:
                # Sliding window chunking for long sections
                step = max(1, chunk_size - overlap)
                for i in range(0, len(para_words), step):
                    window = para_words[i : i + chunk_size]
                    if window:
                        chunk_body = f"[{doc.category}] {doc.title}: {' '.join(window)}"
                        chunks_text.append(chunk_body)

        if not chunks_text and doc.content.strip():
            chunks_text.append(f"[{doc.category}] {doc.title}: {doc.content.strip()}")

        result_chunks: List[CorpusChunk] = []
        for idx, text in enumerate(chunks_text):
            chunk_id = f"{doc.doc_id}#chunk_{idx}"
            words = text.split()
            chunk = CorpusChunk(
                chunk_id=chunk_id,
                doc_id=doc.doc_id,
                content=text,
                source_url=doc.source_url,
                chunk_index=idx,
                token_count=len(words),
                metadata={
                    "title": doc.title,
                    "category": doc.category,
                    "last_updated": doc.last_updated.isoformat(),
                    **doc.metadata,
                },
            )
            result_chunks.append(chunk)

        return result_chunks

    def index_documents(
        self,
        docs: List[CorpusDocument],
        compute_embeddings: bool = True,
    ) -> None:
        """Chunk all documents and construct BM25 and dense embedding indexes."""
        self.documents = {doc.doc_id: doc for doc in docs}
        all_chunks: List[CorpusChunk] = []

        for doc in docs:
            doc_chunks = self.chunk_document(doc)
            all_chunks.extend(doc_chunks)

        self.chunks = all_chunks
        self.tokenized_corpus = [simple_tokenize(chunk.content) for chunk in self.chunks]
        self.bm25 = BM25Okapi(self.tokenized_corpus) if self.tokenized_corpus else None

        if compute_embeddings and self.chunks:
            texts = [chunk.content for chunk in self.chunks]
            raw_embeddings = self.model.encode(
                texts,
                batch_size=32,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            self.chunk_embeddings = np.array(raw_embeddings, dtype=np.float32)

            for i, chunk in enumerate(self.chunks):
                chunk.embedding = self.chunk_embeddings[i].tolist()
        else:
            self.chunk_embeddings = None

    def search_corpus(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[SearchResult]:
        """Perform hybrid BM25 + Dense vector retrieval against indexed corpus.

        Returns ranked list of grounded SearchResult items.
        """
        if not self.chunks or not query.strip():
            return []

        # 1. Lexical BM25 Scoring with Query Term Coverage
        query_tokens = simple_tokenize(query)
        if self.bm25 and query_tokens:
            bm25_raw_scores = np.maximum(
                0.0, np.array(self.bm25.get_scores(query_tokens), dtype=np.float32)
            )
            max_bm25 = np.max(bm25_raw_scores)
            if max_bm25 > 0:
                bm25_norm = bm25_raw_scores / max_bm25
                q_set = set(query_tokens)
                coverage = np.array([
                    len(q_set.intersection(set(self.tokenized_corpus[i]))) / len(q_set) if q_set else 0.0
                    for i in range(len(self.chunks))
                ], dtype=np.float32)
                bm25_scores = bm25_norm * coverage
            else:
                bm25_scores = np.zeros(len(self.chunks), dtype=np.float32)
        else:
            bm25_scores = np.zeros(len(self.chunks), dtype=np.float32)

        # 2. Dense Semantic Vector Scoring
        if self.chunk_embeddings is not None:
            query_embedding = self.model.encode(
                [query],
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )[0]
            dense_scores = np.clip(np.dot(self.chunk_embeddings, query_embedding), 0.0, 1.0)
        else:
            dense_scores = np.zeros(len(self.chunks), dtype=np.float32)

        # 3. Hybrid Fusion
        w_dense = self.settings.HYBRID_DENSE_WEIGHT
        w_bm25 = self.settings.HYBRID_BM25_WEIGHT
        hybrid_scores = (w_dense * dense_scores) + (w_bm25 * bm25_scores)

        # 4. Rank and Filter Results
        top_indices = np.argsort(hybrid_scores)[::-1][:top_k]
        results: List[SearchResult] = []

        for idx in top_indices:
            score = float(hybrid_scores[idx])
            if score < min_score:
                continue

            chunk = self.chunks[idx]
            result = SearchResult(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                content=chunk.content,
                source_url=chunk.source_url,
                score=round(score, 4),
                bm25_score=round(float(bm25_scores[idx]), 4),
                dense_score=round(float(dense_scores[idx]), 4),
                metadata=chunk.metadata,
            )
            results.append(result)

        return results

    def save_index(self, path: Union[str, Path]) -> None:
        """Serialize index state and chunk metadata to disk."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "documents": [doc.model_dump(mode="json") for doc in self.documents.values()],
            "chunks": [chunk.model_dump(mode="json") for chunk in self.chunks],
            "chunk_embeddings": self.chunk_embeddings,
            "embedding_model_name": self.embedding_model_name,
        }

        with open(target_path, "wb") as f:
            pickle.dump(payload, f)
        logger.info("Saved index with %d chunks to %s", len(self.chunks), target_path)

    def load_index(self, path: Union[str, Path]) -> bool:
        """Load serialized index state from disk."""
        target_path = Path(path)
        if not target_path.exists():
            return False

        try:
            with open(target_path, "rb") as f:
                payload = pickle.load(f)

            self.embedding_model_name = payload.get(
                "embedding_model_name", self.settings.EMBEDDING_MODEL_NAME
            )
            docs = [CorpusDocument(**d) for d in payload.get("documents", [])]
            self.documents = {d.doc_id: d for d in docs}

            self.chunks = [CorpusChunk(**c) for c in payload.get("chunks", [])]
            self.tokenized_corpus = [
                simple_tokenize(chunk.content) for chunk in self.chunks
            ]
            self.bm25 = (
                BM25Okapi(self.tokenized_corpus) if self.tokenized_corpus else None
            )
            self.chunk_embeddings = payload.get("chunk_embeddings")
            logger.info("Loaded index with %d chunks from %s", len(self.chunks), target_path)
            return True
        except Exception as e:
            logger.warning("Failed to load cached index from %s: %s", target_path, e)
            return False

    def load_and_index_corpus(
        self,
        corpus_dir: Optional[Union[str, Path]] = None,
        cache_path: Optional[Union[str, Path]] = None,
        force_reindex: bool = False,
    ) -> None:
        """High-level entrypoint: loads documents from directory, indexing with caching."""
        corpus_path = Path(corpus_dir or self.settings.CORPUS_DATA_DIR)
        cache_file = Path(cache_path or self.settings.VECTOR_INDEX_PATH)

        if not force_reindex and cache_file.exists():
            if self.load_index(cache_file):
                return

        documents: List[CorpusDocument] = []
        if not corpus_path.exists():
            raise FileNotFoundError(f"Corpus directory not found: {corpus_path}")

        for file_path in sorted(corpus_path.glob("*.json")):
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                doc = CorpusDocument(**data)
                documents.append(doc)

        if not documents:
            raise ValueError(f"No JSON corpus documents found in {corpus_path}")

        logger.info("Loaded %d documents from %s. Indexing...", len(documents), corpus_path)
        self.index_documents(documents, compute_embeddings=True)
        self.save_index(cache_file)


# Global indexer instance accessor
_corpus_indexer_instance: Optional[CorpusIndexer] = None


def get_corpus_indexer(force_reinit: bool = False) -> CorpusIndexer:
    """Retrieve singleton corpus indexer initialized with Milestone 1 corpus."""
    global _corpus_indexer_instance
    if _corpus_indexer_instance is None or force_reinit:
        indexer = CorpusIndexer()
        indexer.load_and_index_corpus()
        _corpus_indexer_instance = indexer
    return _corpus_indexer_instance
