# Phase-Wise Implementation Plan: Human-in-the-Loop (HITL) Support & Product Intelligence System

## Executive Overview

This implementation plan provides a structured, phase-by-phase engineering roadmap to build, test, and deploy the Human-in-the-Loop (HITL) Support & Product Intelligence System defined in [doc/problemStatement.md](file:///Users/jeevanshu/projects%20form%20nextleaf/Human-in-the-Loop/doc/problemStatement.md) and [doc/architecture.md](file:///Users/jeevanshu/projects%20form%20nextleaf/Human-in-the-Loop/doc/architecture.md).

The system addresses the operational disconnect at an Indian investment platform by running two interconnected feedback loops:
1. **The Response Loop:** Real-time customer support query resolution through a 3-agent parallel mesh, an orchestrator, and a reviewer, producing concise cited drafts ($\le 3$ sentences) and internal routing notes.
2. **The Weekly Loop:** Unattended batch review ingestion, thematic clustering ($\le 5$ themes, top 3 isolated), executive pulse generation ($\le 250$ words, direct quotes with review IDs, 3 action ideas), and canonical fee explainer synthesis ($\le 6$ bullets, $\ge 2$ official links, `last_checked_date`).
3. **The Bi-Directional Bridge:** Approved explainers become canonical answers reused in support; questions seen $\ge 5$ times/week escalate to the weekly product pulse.

### High-Level Roadmap & Milestones

| Phase | Title | Focus Area | Key Deliverable |
| :---: | :--- | :--- | :--- |
| **0** | **Foundations & Corpus Setup** | Environment, Core Schemas, Corpus Indexing | Scaffolded repo, Milestone 1 index, Pydantic schemas |
| **1** | **Safety, Privacy & State Isolation** | Zero-PII Scrubber, Advice Blocker, Diff Engine | PII regex/NER, SEBI guardrails, atomic state diffs |
| **2** | **Response Loop Pipeline** | Parallel Agent Mesh, Orchestrator, Reviewer | 3-agent parallel engine, citation checker, fallback |
| **3** | **Weekly Loop Pipeline** | Review Ingestion, Clustering, Pulse & Explainer | Batch clustering ($\le 5$ themes), pulse ($\le 250$w), explainer |
| **4** | **Bi-Directional Knowledge Bridge** | Canonical Explainer Reuse & Frequency Escalation | Fast-path lookup, sliding-window $\ge 5$/wk trigger |
| **5** | **HITL Web Application & API Gateway** | Support Queue, Product Dashboard, Audit UI | Full-stack interactive web app with 1-click approvals |
| **6** | **End-to-End Audit & Verification** | 15-Claim Audit, Adversarial Testing, Deployment | E2E test suite, audit verification script, Docker setup |

---

## Phase 0: Foundations, Core Data Schemas & Milestone 1 Corpus Setup

### Objective
Establish the project workspace, runtime environment, dependency management, shared data models, and the Milestone 1 official public documentation corpus with hybrid retrieval (BM25 + Dense Vectors).

### Key Files to Create
- `pyproject.toml` / `requirements.txt`: Python 3.11+ dependencies (`fastapi`, `uvicorn`, `pydantic`, `sentence-transformers`, `rank-bm25`, `scikit-learn`, `pytest`, `httpx`).
- `.env.example`: Configuration variables (vector store paths, embedding model names, environment flags).
- `src/config.py`: Centralized application settings using `pydantic-settings`.
- `src/models/`: Pydantic data schemas for all system entities:
  - `corpus.py`: `CorpusDocument`, `CorpusChunk`, `SearchResult`
  - `review.py`: `UserReview`, `ThemeCluster`, `WeeklyPulse`
  - `explainer.py`: `CanonicalExplainer`
  - `ticket.py`: `SupportTicket`, `AgentDeliberation`, `RoutingNote`
  - `audit.py`: `AuditDiffLog`, `StateDiff`
- `data/corpus/`: Raw and parsed Milestone 1 official public documents (brokerage schedules, STT/GST circulars, DP charge explainers, account opening terms).
- `src/retrieval/corpus_indexer.py`: Document parser, chunker, metadata tagger, and indexer (BM25 + Dense vector embeddings).
- `tests/test_phase0.py`: Verification tests for schemas, corpus loading, and baseline retrieval.

### Step-by-Step Tasks
1. **Initialize Project Skeleton & Environment:**
   - Configure virtual environment, linting rules, and `.gitignore`.
   - Setup project structure (`src/`, `data/`, `tests/`, `static/`).
2. **Implement Core Pydantic Models:**
   - Enforce type hints, field validations, and strict schema serializations.
   - Include constraints (e.g. `word_count` checks, bullet list lengths, URL formats).
3. **Curate Milestone 1 Official Corpus:**
   - Collect and structure official public disclosures (e.g. zero-brokerage equity delivery terms, F&O brokerage tariffs, CDSL/NSDL DP charges, SEBI turnover fees, stamp duty).
   - Tag each document with immutable metadata: `doc_id`, `title`, `source_url`, `category`, and `last_updated`.
4. **Build Hybrid Corpus Indexer:**
   - Implement semantic text chunking (chunk size: 250–400 tokens with 50-token overlap).
   - Generate embeddings using a lightweight local embedding model (`all-MiniLM-L6-v2`).
   - Build a synchronized lexical index using `rank-bm25`.
   - Implement `search_corpus(query, top_k)` returning grounded chunks with source URLs.

### Verification & Exit Criteria
- `pytest tests/test_phase0.py` passes with 100% coverage on schema validation.
- Milestone 1 corpus index queries return exact official source links with relevance scores.

---

## Phase 1: Security, PII Sanitization, SEBI Compliance & State Isolation Diff Engine

### Objective
Implement deterministic security perimeter defenses: multi-pattern Indian PII scrubbing, SEBI financial advisory blocks, and cryptographic state isolation tracking for all human actions.

### Key Files to Create
- `src/security/pii_scrubber.py`: Two-stage PII sanitizer (Regex patterns + Entity rules for PAN, Indian Mobile, Aadhaar, Demat/Account, Email).
- `src/security/compliance_guard.py`: Financial advice and performance projection classifier rejecting recommendations deterministically.
- `src/storage/state_diff_engine.py`: Cryptographic entity hashing, state capture, and single-entity JSON patch diff validator.
- `tests/test_phase1.py`: Unit and adversarial tests for PII redaction, advice refusal, and state isolation invariants.

### Step-by-Step Tasks
1. **Implement Two-Stage PII Scrubber:**
   - Stage 1: Fast regex masking for Indian financial identifiers:
     - PAN: `[A-Z]{5}[0-9]{4}[A-Z]` $\rightarrow$ `[REDACTED_PAN]`
     - Mobile: `(?:\+91[\-\s]?)?[6-9]\d{9}` $\rightarrow$ `[REDACTED_PHONE]`
     - Aadhaar: `\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b` $\rightarrow$ `[REDACTED_AADHAAR]`
     - Demat/Account: `\b\d{8,16}\b` $\rightarrow$ `[REDACTED_ACCOUNT]`
     - Email: `[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+` $\rightarrow$ `[REDACTED_EMAIL]`
   - Stage 2: Name and location masking via entity boundaries.
   - Enforce that unredacted inputs never touch persistence, logs, or agent prompts.
2. **Implement SEBI Compliance & Advice Refusal Engine:**
   - Keyword and semantic intent detector for advisory language: `buy`, `sell`, `target price`, `expected return`, `recommend`, `multibagger`.
   - Provide standard regulatory refusal response citing platform fee disclosures only.
3. **Build State Isolation & Diff Engine:**
   - Implement `capture_state(entity_id)` returning an immutable snapshot and SHA-256 hash.
   - Implement `compute_diff(pre_state, post_state)` generating standard RFC 6902 JSON patches.
   - Invariant validator: Ensure human actions on Ticket $T_i$ touch *only* $T_i$ and no sibling records or global states.
   - Append-only audit logger writing to `audit_diff_log`.

### Verification & Exit Criteria
- `pytest tests/test_phase1.py` confirms 100% redaction across variations of PAN, phone, and account numbers.
- Financial advice prompts are refused 100% of the time with regulatory fallback text.
- State mutation diff test confirms that updating an item mutates only that single entity ID.

---

## Phase 2: Response Loop Pipeline (Parallel Multi-Agent Support Drafting)

### Objective
Construct the customer support query processing engine: 3-agent parallel pipeline, orchestrator synthesis, reviewer quality control, citation mapping, and explicit "not covered" fallback protocol.

### Key Files to Create
- `src/agents/response/retrieval_agent.py`: Agent 1 querying Milestone 1 corpus, assessing relevance threshold, and formatting citations.
- `src/agents/response/compliance_agent.py`: Agent 2 checking SEBI guidelines, facts-only constraint, and absence of speculative claims.
- `src/agents/response/drafting_agent.py`: Agent 3 formulating initial concise draft and structured internal routing note.
- `src/agents/response/orchestrator.py`: Multi-agent fan-out coordinator combining signals and detecting fallback conditions.
- `src/agents/response/reviewer_agent.py`: Quality gate enforcing $\le 3$ sentences, exactly 1 corpus citation, and zero PII leaks.
- `src/agents/response/pipeline.py`: End-to-end response loop orchestrator connecting ingress to final review draft.
- `tests/test_phase2.py`: Automated tests for parallel execution, sentence limits, citations, and fallback behavior.

### Step-by-Step Tasks
1. **Implement Agent 1 (Corpus Retrieval Specialist):**
   - Execute hybrid search against Milestone 1 index with relevance threshold $\tau_{rel} = 0.72$.
   - If below threshold, trigger "Not Covered" flag and preserve the exact search terms evaluated.
2. **Implement Agent 2 (Compliance & Policy Guard):**
   - Inspect query and candidate answers for regulatory breaches (guaranteed returns, advice).
3. **Implement Agent 3 (Synthesis & Drafting Agent):**
   - Synthesize factual answer strictly from retrieved snippets.
   - Generate internal routing note: `category`, `urgency`, `sentiment`, and `reason`.
4. **Implement Orchestrator Agent:**
   - Concurrently execute Agents 1, 2, and 3 (`asyncio.gather`).
   - Resolve disagreements; if Agent 1 flags "not covered", format standard fallback:
     *"This question is not covered in our official platform documentation. Search evaluated: ['<query 1>', '<query 2>']."*
5. **Implement Reviewer Agent (Quality Gate):**
   - Sentence segmentation enforcing count $\le 3$.
   - Verify presence of exactly one whitelisted Milestone 1 source URL.
   - Verify complete absence of PII and advisory language.

### Verification & Exit Criteria
- `pytest tests/test_phase2.py` passes:
  - 100% of valid questions produce $\le 3$ sentences with an official source link.
  - 100% of uncovered questions trigger the explicit "not covered" message with searched terms.
  - Internal routing note contains valid category, urgency, and reason fields.

---

## Phase 3: Weekly Loop Pipeline (Unattended Batch Ingestion, Clustering & Pulse)

### Objective
Build the unattended Weekly Loop that ingests customer reviews, clusters them into at most 5 themes, extracts the top 3 themes and recurring fee friction, and produces an executive Weekly Pulse ($\le 250$ words) and Canonical Fee Explainer ($\le 6$ bullets).

### Key Files to Create
- `src/agents/weekly/review_ingest.py`: Review batch loader, PII sanitizer, and date-window segmenter.
- `src/agents/weekly/clustering_engine.py`: Vector embedding + constrained clustering engine ($\le 5$ themes) with review ID lineage.
- `src/agents/weekly/pulse_generator.py`: Executive summary generator enforcing $\le 250$ words, direct quotes with review IDs, and 3 concrete action ideas.
- `src/agents/weekly/explainer_generator.py`: Canonical fee explainer synthesizer ($\le 6$ bullets, $\ge 2$ official links, `last_checked_date`).
- `src/agents/weekly/runner.py`: Unattended scheduler/runner executing the loop end-to-end without user prompts.
- `tests/test_phase3.py`: Automated tests verifying unattended execution, cap constraints, word counts, and quote-to-review-ID lineage.

### Step-by-Step Tasks
1. **Implement Review Ingestion & Sanitization:**
   - Ingest review batches within window $[T_{start}, T_{end}]$; assign immutable `review_id`s.
   - Run PII scrubber across all review texts.
2. **Build Thematic Clustering Engine:**
   - Compute text embeddings for all sanitized reviews in the batch.
   - Apply constrained clustering (K-Means / HDBSCAN) configured for a hard cap of $K \le 5$ themes.
   - Isolate the Top 3 themes by volume and negative sentiment.
   - Detect and extract the primary recurring fee/charge friction sub-theme.
   - Retain full lineage mapping each cluster to its constituent `review_id` list.
3. **Implement Weekly Pulse Generator:**
   - Synthesize executive report constrained to $\le 250$ words.
   - Extract 2–3 verbatim user quotes with direct parenthetical citations `(Review #ID)`.
   - Generate exactly three (3) actionable product improvement ideas.
4. **Implement Canonical Fee Explainer Generator:**
   - Query Milestone 1 corpus using the identified recurring fee confusion topic.
   - Synthesize a clear explainer formatted into $\le 6$ bullet points.
   - Ground explainer with $\ge 2$ official Milestone 1 documentation links.
   - Inject current ISO-8601 `last_checked_date`.
5. **Implement Unattended Pipeline Runner:**
   - Package the pipeline into a single non-interactive execution call that runs to completion.

### Verification & Exit Criteria
- `pytest tests/test_phase3.py` passes:
  - Weekly Pulse word count $\le 250$ words.
  - Canonical Explainer bullet count $\le 6$ with $\ge 2$ valid official source links.
  - Clusters $\le 5$ with top 3 identified.
  - 100% of quotes trace back to legitimate review IDs in the dataset.
  - Pipeline executes unattended from start to finish.

---

## Phase 4: Bi-Directional Bridge & Knowledge Synchronization

### Objective
Connect the two operational halves: enable the Response Loop to reuse product-approved canonical fee explainers, and enable the Weekly Loop to receive high-frequency support inquiry escalations ($\ge 5$ times/week).

### Key Files to Create
- `src/bridge/canonical_store.py`: Knowledge base storing human-approved Canonical Explainers with embedding indices and fast-path retrieval.
- `src/bridge/frequency_tracker.py`: Sliding-window support question frequency monitor tracking recurring topics.
- `src/bridge/sync_coordinator.py`: Bi-directional bridge coordinator managing explainer invalidation and high-frequency escalation triggers.
- `tests/test_phase4.py`: Integration tests for canonical explainer lookup, zero-shot reuse, and $\ge 5$/wk escalation to the Weekly Pulse.

### Step-by-Step Tasks
1. **Implement Canonical Explainer Store & Fast-Path Retrieval:**
   - Store human-approved explainers with topic slugs, bullet points, source links, and embeddings.
   - Integrate fast-path check into Response Loop: if cosine similarity $> 0.88$, reuse the canonical explanation rather than drafting fresh.
2. **Implement Question Frequency Tracker:**
   - Normalize and cluster incoming support questions in a sliding 7-day window.
   - Count topic frequencies; if frequency $count(topic) \ge 5$, trigger an escalation event.
3. **Integrate Escalation with Weekly Loop:**
   - Ingest escalated topics into the Weekly Pulse generator as an empirical "High-Frequency Support Issues" section.
4. **Verify Bi-Directional Synchronization:**
   - Prove that approving an explainer in the Weekly Loop immediately updates Response Loop behavior without restart.

### Verification & Exit Criteria
- `pytest tests/test_phase4.py` passes:
  - Inquiries matching an approved explainer reuse canonical text and bypass fresh drafting.
  - Inquiries submitted $\ge 5$ times in a simulated week are flagged and appear in the next Weekly Pulse draft.

---

## Phase 5: Human-in-the-Loop (HITL) Web Application & API Gateway

### Objective
Build and deploy the interactive Human-in-the-Loop web application, providing role-specific workflows for Support Specialists, Product Managers, and Compliance Auditors.

### Key Files to Create
- `src/api/app.py`: FastAPI server with CORS, routing, and lifecycle handlers.
- `src/api/routes/support.py`: Endpoints for support queue: fetch tickets, inspect agent deliberations, edit drafts, approve & send, reject.
- `src/api/routes/product.py`: Endpoints for product portal: fetch weekly pulse, inspect themes/quotes, review and approve canonical explainers.
- `src/api/routes/audit.py`: Endpoints for audit logs and state diff inspection.
- `src/static/index.html`: Responsive single-page application shell with rich, modern design.
- `src/static/css/style.css`: Modern styling (vanilla CSS, sleek dark mode, clear typography, micro-animations).
- `src/static/js/app.js`: Client-side reactivity, real-time status updates, inline editing with live sentence/link validation, and state diff rendering.
- `tests/test_phase5.py`: Integration tests for API endpoints, HTTP status codes, and client action workflows.

### Step-by-Step Tasks
1. **Develop FastAPI Backend Endpoints:**
   - Implement REST endpoints for queue management, pulse reviews, and audit history.
   - Wrap every mutating action in the State Diff Engine, verifying atomic mutation before commit.
2. **Build Support Queue Interface:**
   - Queue list showing status badges (`PENDING_APPROVAL`, `APPROVED`, `EDITED`, `REJECTED`, `NOT_COVERED`).
   - Detailed inspection drawer: original sanitized query, multi-agent evaluation cards, editable draft box.
   - Live client-side validator enforcing $\le 3$ sentences and $\ge 1$ source link before enabling "Approve" button.
   - Display internal routing note (category, urgency, reason).
3. **Build Product Intelligence Interface:**
   - Weekly Pulse card with formatted word-count meter ($\le 250$w).
   - Interactive quote cards linking directly to raw review IDs.
   - Canonical Explainer card with 1-click "Approve into Canonical Store" button.
4. **Build State Diff & Audit Interface:**
   - Visual before/after JSON diff viewer displaying exact patch operations for every action.
5. **Style & Polish UI:**
   - Implement clean aesthetics, modern typography, responsive cards, and accessible interactive elements.

### Verification & Exit Criteria
- `pytest tests/test_phase5.py` verifies all API endpoints and mutation diff integrity.
- Web UI allows human operators to edit, approve, or reject drafts with instant visual confirmation.

---

## Phase 6: End-to-End Verification, 15-Claim Audit & Deployment Readiness

### Objective
Execute comprehensive system validation against all problem statement success criteria, run the 15-claim grounding audit, test adversarial edge cases, and prepare production deployment packaging.

### Key Files to Create
- `scripts/verify_claims_audit.py`: Automated audit script sampling 15 factual claims across both loops and verifying exact lineage.
- `scripts/adversarial_security_test.py`: Penetration test script evaluating PII leakage and SEBI advice refusal across rephrased prompts.
- `tests/test_e2e.py`: Full end-to-end integration test exercising the complete lifecycle across both loops.
- `Dockerfile` / `docker-compose.yml`: Containerization specification for reproducible deployment.
- `README.md`: System documentation, setup guide, and operational runbook.

### Step-by-Step Tasks
1. **Execute 15-Claim Grounding & Lineage Audit:**
   - Sample 15 distinct factual claims across generated response drafts, weekly pulse summaries, and fee explainers.
   - Programmatically verify that every claim resolves to either:
     - An official whitelisted Milestone 1 source URL, or
     - A verified `review_id` within the active dataset.
2. **Execute Adversarial PII & Compliance Pen-Test:**
   - Test queries embedding obfuscated PAN numbers (e.g. `A B C D E 1 2 3 4 F`), spaced phone numbers, and demat IDs.
   - Test advisory prompts (e.g. *"Suggest best stocks for 2026"*, *"Will Nifty hit 30,000?"*).
   - Assert 100% refusal or sanitization; confirm zero leakage in logs or state diffs.
3. **Execute Full End-to-End Test Suite:**
   - Run entire automated test suite (`tests/test_phase*.py` + `tests/test_e2e.py`).
4. **Package for Deployment:**
   - Configure container image and runtime startup scripts.

### Verification & Exit Criteria
- 15/15 claims in audit pass strict source lineage verification.
- 100% pass rate on adversarial PII and financial advice tests.
- Full test suite passes cleanly with zero regressions.

---

## Traceability Matrix: Success Criteria to Implementation Phases

| Success Criteria (from Problem Statement) | Covered In | Verification Mechanism |
| :--- | :--- | :--- |
| **Every question answered or explained ($\le 3$ sentences or explicit "not covered" with searched queries)** | Phase 2, Phase 5 | `tests/test_phase2.py`, Reviewer Agent sentence tokenizer, Fallback logger |
| **Weekly loop runs unattended within caps ($\le 250$w pulse, $\le 6$ bullets, $\le 5$ themes, quotes trace to review IDs)** | Phase 3 | `tests/test_phase3.py`, Unattended runner, Word & bullet counter |
| **Edits and approvals stay contained (diff of system state confirms only target item mutated)** | Phase 1, Phase 5 | `tests/test_phase1.py`, `StateDiffEngine` JSON patch validator |
| **Grounded claims & zero sensitive leaks (15-claim audit, 100% PII/advice refusal and redaction)** | Phase 1, Phase 6 | `scripts/verify_claims_audit.py`, `scripts/adversarial_security_test.py` |
| **Bi-directional connection (canonical explainer reuse, $\ge 5$x/wk escalation)** | Phase 4 | `tests/test_phase4.py`, Canonical store fast matcher, Frequency tracker |
