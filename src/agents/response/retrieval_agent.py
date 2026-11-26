"""Agent 1: Corpus Retrieval Specialist querying Milestone 1 disclosures."""

import logging
import re
from typing import Any, Dict, List, Optional
from src.config import Settings, get_settings
from src.models.corpus import SearchResult
from src.retrieval.corpus_indexer import CorpusIndexer, get_corpus_indexer

logger = logging.getLogger(__name__)


class RetrievalAgent:
    """Agent 1 querying Milestone 1 corpus, assessing relevance threshold, and formatting citations."""

    ACRONYM_MAP = [
        (re.compile(r"\bSTT\b", re.IGNORECASE), "Securities Transaction Tax"),
        (re.compile(r"\bDP\b", re.IGNORECASE), "Depository Participant"),
        (re.compile(r"\bAMC\b", re.IGNORECASE), "Annual Maintenance Charge"),
        (re.compile(r"\bBSDA\b", re.IGNORECASE), "Basic Services Demat Account"),
    ]

    def __init__(
        self,
        indexer: Optional[CorpusIndexer] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.indexer = indexer or get_corpus_indexer()
        self.threshold = self.settings.RETRIEVAL_SIMILARITY_THRESHOLD

    def _expand_acronyms(self, text: str) -> str:
        """Expand common capital market acronyms to improve hybrid retrieval recall."""
        expanded = text
        for pattern, full_term in self.ACRONYM_MAP:
            if pattern.search(expanded) and full_term.lower() not in expanded.lower():
                expanded = f"{expanded} {full_term}"
        return expanded

    def evaluate_query(self, query: str, top_k: int = 3) -> Dict[str, Any]:
        """Execute hybrid search against Milestone 1 corpus and evaluate coverage against threshold."""
        clean_query = query.strip()
        searched_queries = [clean_query]

        if not clean_query:
            return {
                "covered": False,
                "relevance_score": 0.0,
                "chunks": [],
                "top_chunk": None,
                "source_url": None,
                "searched_queries": searched_queries,
                "reason": "Empty query provided.",
                "partial_gap": None,
            }

        # 1. Primary hybrid search
        expanded_primary = self._expand_acronyms(clean_query)
        if expanded_primary != clean_query and expanded_primary not in searched_queries:
            searched_queries.append(expanded_primary)

        results = self.indexer.search_corpus(expanded_primary, top_k=top_k)
        top_chunk = results[0] if results else None
        top_score = top_chunk.score if top_chunk else 0.0

        # 2. Decompose conversational or multi-sentence inquiries (e.g. greetings or redacted PII prefaces)
        # If score is below threshold and there are multiple sentences, evaluate individual sentences
        sub_sentences = [
            s.strip()
            for s in re.split(r"[.!?]+", clean_query)
            if len(s.strip()) > 5 and not re.fullmatch(r"\[REDACTED_[A-Z_]+\]", s.strip())
        ]
        if len(sub_sentences) > 1 and top_score < self.threshold:
            for sent in sub_sentences:
                expanded_sent = self._expand_acronyms(sent)
                if expanded_sent not in searched_queries:
                    searched_queries.append(expanded_sent)
                sub_res = self.indexer.search_corpus(expanded_sent, top_k=top_k)
                if sub_res and sub_res[0].score > top_score:
                    top_score = sub_res[0].score
                    top_chunk = sub_res[0]
                    results = sub_res

        # 3. Check for multi-part or compound queries (e.g. EC-RAG-01: 'Part A and Part B')
        sub_query_gaps: List[str] = []
        if " and " in clean_query.lower() or " as well as " in clean_query.lower():
            # Split compound query into sub-intents
            parts = [
                p.strip()
                for p in re.split(r"\s+(?:and|as well as)\s+", clean_query, flags=re.IGNORECASE)
                if len(p.strip()) > 5
            ]
            for part in parts:
                exp_part = self._expand_acronyms(part)
                sub_res = self.indexer.search_corpus(exp_part, top_k=1)
                sub_score = sub_res[0].score if sub_res else 0.0
                if sub_score < self.threshold:
                    sub_query_gaps.append(part)
                    if part not in searched_queries:
                        searched_queries.append(part)
                else:
                    # If primary search failed but a valid sub-intent succeeded
                    if sub_score > top_score:
                        top_score = sub_score
                        top_chunk = sub_res[0]
                        results = sub_res

        # 4. Evaluate overall coverage against threshold
        if top_score < self.threshold:
            logger.info(
                "Query below relevance threshold %.2f (score=%.4f): '%s'",
                self.threshold, top_score, clean_query
            )
            return {
                "covered": False,
                "relevance_score": top_score,
                "chunks": results,
                "top_chunk": None,
                "source_url": None,
                "searched_queries": searched_queries,
                "reason": f"Relevance score ({top_score:.4f}) fell below official threshold ({self.threshold}).",
                "partial_gap": None,
            }

        # If top score cleared threshold but a compound sub-query failed
        if sub_query_gaps:
            return {
                "covered": True,
                "relevance_score": top_score,
                "chunks": results,
                "top_chunk": top_chunk,
                "source_url": top_chunk.source_url if top_chunk else None,
                "searched_queries": searched_queries,
                "reason": "Primary intent covered, but secondary sub-intent uncovered.",
                "partial_gap": sub_query_gaps[0],
            }

        return {
            "covered": True,
            "relevance_score": top_score,
            "chunks": results,
            "top_chunk": top_chunk,
            "source_url": top_chunk.source_url if top_chunk else None,
            "searched_queries": searched_queries,
            "reason": f"Top match cleared threshold with score {top_score:.4f}.",
            "partial_gap": None,
        }

