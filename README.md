# Human-in-the-Loop (HITL) Support & Product Intelligence System

A dual-loop, multi-agent AI system with strict Human-in-the-Loop (HITL) controls bridging Customer Support and Product Intelligence for an Indian investment platform.

## Architecture Overview

1. **Response Loop:** Real-time customer support query resolution through a 3-agent parallel mesh, an orchestrator, and a reviewer, producing concise cited drafts ($\le 3$ sentences) and internal routing notes.
2. **Weekly Loop:** Unattended batch review ingestion, thematic clustering ($\le 5$ themes, top 3 isolated), executive pulse generation ($\le 250$ words, direct quotes with review IDs, 3 action ideas), and canonical fee explainer synthesis ($\le 6$ bullets, $\ge 2$ official links, `last_checked_date`).
3. **Bi-Directional Bridge:** Approved explainers become canonical answers reused in support; questions seen $\ge 5$ times/week escalate to the weekly product pulse.

## Project Structure

```
├── doc/                        # Architectural and operational specifications
├── data/
│   ├── corpus/                 # Milestone 1 official public documentation
│   └── index/                  # Cached hybrid BM25 and dense embeddings index
├── src/
│   ├── config.py               # Centralized configuration via pydantic-settings
│   ├── models/                 # Pydantic schemas for all entities
│   │   ├── corpus.py           # CorpusDocument, CorpusChunk, SearchResult
│   │   ├── review.py           # UserReview, ThemeCluster, WeeklyPulse
│   │   ├── explainer.py        # CanonicalExplainer
│   │   ├── ticket.py           # SupportTicket, AgentDeliberation, RoutingNote
│   │   └── audit.py            # AuditDiffLog, StateDiff, PatchOperation
│   └── retrieval/              # Document chunker, BM25, and dense vector indexer
│       └── corpus_indexer.py
├── tests/                      # Automated test suite
│   └── test_phase0.py          # Phase 0 verification tests
├── static/                     # Web application UI assets
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Build & dependency metadata
└── .env.example                # Configuration environment variables template
```

## Setup & Execution

### 1. Environment Setup
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Phase 0 Verification Tests
```bash
pytest tests/test_phase0.py -v
```
