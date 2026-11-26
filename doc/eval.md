# Evaluation Rubric: Human-in-the-Loop (HITL) Support & Product Intelligence System

## Document Context

This evaluation document is derived from the phase-wise [implementation plan](file:///Users/jeevanshu/projects%20form%20nextleaf/Human-in-the-Loop/doc/implementation-plan.md), the [problem statement](file:///Users/jeevanshu/projects%20form%20nextleaf/Human-in-the-Loop/doc/problemStatement.md), and the [system architecture specification](file:///Users/jeevanshu/projects%20form%20nextleaf/Human-in-the-Loop/doc/architecture.md). It provides a structured, objective rubric for evaluating the completeness, correctness, and quality of the implementation across all seven phases (Phase 0–6).

---

## 1. Scoring Framework

Each evaluation criterion is scored on a **4-point scale**:

| Score | Label | Definition |
| :---: | :--- | :--- |
| **4** | **Excellent** | Fully implemented, well-tested, exceeds specification with robust edge-case handling. |
| **3** | **Satisfactory** | Fully implemented and passes all stated verification criteria with minor polish gaps. |
| **2** | **Partial** | Core functionality present but incomplete; some verification criteria not met. |
| **1** | **Minimal** | Skeleton or stub implementation only; major functionality missing. |
| **0** | **Not Attempted** | No evidence of implementation for this criterion. |

**Overall Phase Score** = (Sum of criterion scores) / (Max possible score) × 100%

---

## 2. Phase 0: Foundations, Core Data Schemas & Corpus Setup

**Weight: 15%**
**Objective:** Establish project workspace, runtime environment, shared data models, and the Milestone 1 corpus with hybrid retrieval.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 0.1 | **Project Skeleton & Environment** — `pyproject.toml` or `requirements.txt` present with all specified dependencies (FastAPI, Uvicorn, Pydantic, sentence-transformers, rank-bm25, scikit-learn, pytest, httpx). Virtual environment configurable. `.gitignore` present. | 4 | Dependency manifest, working `pip install`, directory structure matches `src/`, `data/`, `tests/`, `static/`. |
| 0.2 | **Configuration Management** — `.env.example` with documented variables; `src/config.py` using `pydantic-settings` for centralized, validated configuration. | 4 | `.env.example` lists vector store paths, embedding model names, environment flags. `config.py` loads and validates them. |
| 0.3 | **Pydantic Data Models** — All specified schemas implemented with strict type hints, field validations, and serialization constraints: `CorpusDocument`, `CorpusChunk`, `SearchResult`, `UserReview`, `ThemeCluster`, `WeeklyPulse`, `CanonicalExplainer`, `SupportTicket`, `AgentDeliberation`, `RoutingNote`, `AuditDiffLog`, `StateDiff`. | 4 | Models enforce constraints (word count checks, bullet list lengths, URL formats). Schema validation tests pass 100%. |
| 0.4 | **Milestone 1 Corpus Curation** — Official public documents collected, structured, and tagged with immutable metadata (`doc_id`, `title`, `source_url`, `category`, `last_updated`). Covers brokerage schedules, STT/GST circulars, DP charges, account opening terms. | 4 | `data/corpus/` contains tagged documents. Each document has complete metadata fields. |
| 0.5 | **Hybrid Corpus Indexer** — Semantic chunking (250–400 tokens, 50-token overlap), dense embeddings (`all-MiniLM-L6-v2`), BM25 lexical index. `search_corpus(query, top_k)` returns grounded chunks with source URLs and relevance scores. | 4 | `src/retrieval/corpus_indexer.py` implements chunker + dual index. Query returns exact official source links with scores. |
| 0.6 | **Phase 0 Tests** — `tests/test_phase0.py` passes with 100% coverage on schema validation and baseline retrieval verification. | 4 | `pytest tests/test_phase0.py` exits cleanly with all assertions passing. |

**Phase 0 Total: /24**

---

## 3. Phase 1: Security, PII Sanitization, SEBI Compliance & State Isolation

**Weight: 15%**
**Objective:** Implement deterministic security defenses: multi-pattern Indian PII scrubbing, SEBI advisory refusal, and cryptographic state isolation tracking.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 1.1 | **Stage 1: Regex PII Masking** — Correctly identifies and redacts: PAN (`[A-Z]{5}[0-9]{4}[A-Z]` → `[REDACTED_PAN]`), Indian Mobile (`(?:\+91[\-\s]?)?[6-9]\d{9}` → `[REDACTED_PHONE]`), Aadhaar (`\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b` → `[REDACTED_AADHAAR]`), Demat/Account (`\b\d{8,16}\b` → `[REDACTED_ACCOUNT]`), Email → `[REDACTED_EMAIL]`. | 4 | 100% redaction across variations including spacing, dashes, and embedded text. |
| 1.2 | **Stage 2: Entity-Based PII Masking** — Names and location masking via entity boundary detection (NER or heuristic rules). | 4 | Demonstrates name/location redaction on sample inputs. |
| 1.3 | **PII Storage Enforcement** — Unredacted inputs never reach persistence layer, logs, or agent prompts. | 4 | Code audit confirms sanitization occurs at ingress before any storage or logging call. |
| 1.4 | **SEBI Compliance & Advice Refusal** — Keyword + semantic intent detector blocks advisory language (`buy`, `sell`, `target price`, `expected return`, `recommend`, `multibagger`). Deterministic refusal response citing platform fee disclosures only. | 4 | 100% refusal rate on advisory prompts including adversarial rephrasing. Standard refusal template used. |
| 1.5 | **State Diff Engine — `capture_state(entity_id)`** — Returns immutable snapshot with SHA-256 hash. | 4 | Function returns consistent hash for same state; different hash for different states. |
| 1.6 | **State Diff Engine — `compute_diff(pre, post)`** — Generates standard RFC 6902 JSON patches. Invariant validator confirms human actions on Ticket $T_i$ touch only $T_i$. | 4 | Diff correctly identifies add/remove/replace operations. Cross-entity mutation raises `StateIsolationError`. |
| 1.7 | **Append-Only Audit Logger** — All state mutations written to `audit_diff_log` with timestamp, operator, entity type/ID, pre/post hashes, and JSON diff. | 4 | Audit log entries match the specified schema. Log is append-only (no deletions or overwrites). |
| 1.8 | **Phase 1 Tests** — `tests/test_phase1.py` passes: 100% PII redaction, 100% advice refusal, state isolation invariant validated. | 4 | `pytest tests/test_phase1.py` exits cleanly with all assertions passing. |

**Phase 1 Total: /32**

---

## 4. Phase 2: Response Loop Pipeline (Parallel Multi-Agent Support Drafting)

**Weight: 20%**
**Objective:** Construct the 3-agent parallel pipeline, orchestrator synthesis, reviewer quality control, citation mapping, and fallback protocol.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 2.1 | **Agent 1 (Corpus Retrieval Specialist)** — Executes hybrid search with relevance threshold τ_rel = 0.72. Below threshold triggers "Not Covered" flag with exact search terms preserved. | 4 | Returns `covered: false` with `searched_queries` list when threshold not met. Returns grounded chunks with source URLs when met. |
| 2.2 | **Agent 2 (Compliance & Policy Guard)** — Inspects query and candidate answers for regulatory breaches. Forces refusal template when advisory language detected. | 4 | Blocks all advisory language variants. Clean questions pass through unmodified. |
| 2.3 | **Agent 3 (Synthesis & Drafting Agent)** — Synthesizes factual answer strictly from retrieved corpus snippets. Generates internal routing note with valid `category`, `urgency`, `sentiment`, and `reason`. | 4 | Draft uses only provided context. Routing note fields match allowed enum values. |
| 2.4 | **Orchestrator Agent** — Concurrently executes Agents 1, 2, 3 via `asyncio.gather`. Resolves disagreements. Formats standard fallback when Agent 1 flags "not covered." | 4 | Parallel execution demonstrable (timing or logging evidence). Fallback format matches specification. |
| 2.5 | **Reviewer Agent (Quality Gate)** — Sentence segmentation enforcing ≤3 sentences. Verifies exactly one whitelisted Milestone 1 source URL. Verifies complete absence of PII and advisory language. | 4 | Rejects drafts exceeding 3 sentences. Rejects drafts without exactly 1 valid source URL. Catches residual PII. |
| 2.6 | **End-to-End Pipeline Integration** — `src/agents/response/pipeline.py` connects ingress → PII scrub → agents → orchestrator → reviewer → final draft. | 4 | Single function call processes raw query to reviewed draft with all intermediate steps executed. |
| 2.7 | **Phase 2 Tests** — `tests/test_phase2.py` passes: 100% valid questions produce ≤3 sentences + source link; 100% uncovered questions trigger fallback; routing notes contain valid fields. | 4 | `pytest tests/test_phase2.py` exits cleanly with all assertions passing. |

**Phase 2 Total: /28**

---

## 5. Phase 3: Weekly Loop Pipeline (Unattended Batch Ingestion, Clustering & Pulse)

**Weight: 15%**
**Objective:** Build the unattended Weekly Loop: review ingestion, thematic clustering (≤5 themes), executive pulse (≤250 words), and canonical fee explainer (≤6 bullets).

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 3.1 | **Review Ingestion & Sanitization** — Batch ingestion within window [T_start, T_end]. Immutable `review_id` assignment. PII scrubber applied to all review texts. | 4 | Reviews loaded with correct date window filtering. All PII redacted. Each review has a unique, stable ID. |
| 3.2 | **Thematic Clustering Engine** — Vector embeddings computed. Constrained clustering (K-Means / HDBSCAN) with hard cap K ≤ 5 themes. Top 3 themes isolated by volume + negative sentiment. Recurring fee friction sub-theme explicitly extracted. | 4 | Cluster count ≤ 5. Top 3 identified. Fee confusion theme present. Full lineage mapping from cluster → constituent `review_id` list. |
| 3.3 | **Weekly Pulse Generator** — Executive report ≤250 words. Contains 2–3 verbatim user quotes with parenthetical citations `(Review #ID)`. Exactly 3 actionable product improvement ideas. | 4 | Word count verified ≤250. Quotes trace to legitimate review IDs. Exactly 3 action ideas present. |
| 3.4 | **Canonical Fee Explainer Generator** — Queries Milestone 1 corpus for fee confusion topic. ≤6 bullet points. ≥2 official documentation links. Current ISO-8601 `last_checked_date`. | 4 | Bullet count ≤6. Source links verified against corpus. Date stamp in correct format. |
| 3.5 | **Unattended Pipeline Runner** — Pipeline packaged into a single non-interactive execution call. Runs start-to-finish without user prompts. | 4 | Runner executes without blocking for input. All outputs produced in one invocation. |
| 3.6 | **Phase 3 Tests** — `tests/test_phase3.py` passes all constraints: word count, bullet count, cluster count, quote lineage, unattended execution. | 4 | `pytest tests/test_phase3.py` exits cleanly with all assertions passing. |

**Phase 3 Total: /24**

---

## 6. Phase 4: Bi-Directional Bridge & Knowledge Synchronization

**Weight: 10%**
**Objective:** Connect both loops: canonical explainer reuse in Response Loop, and ≥5×/week frequency escalation to Weekly Loop.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 4.1 | **Canonical Explainer Store & Fast-Path Retrieval** — Stores human-approved explainers with topic slugs, bullets, source links, and embeddings. Fast-path check: cosine similarity >0.88 triggers canonical reuse. | 4 | Matching queries reuse canonical text. Non-matching queries proceed to fresh drafting. Similarity threshold correctly applied. |
| 4.2 | **Question Frequency Tracker** — Sliding 7-day window. Normalizes and clusters incoming support questions. Triggers escalation event when count(topic) ≥ 5. | 4 | Topic frequency accurately counted. Escalation triggered at threshold ≥5. Window correctly rolls over time. |
| 4.3 | **Escalation Integration with Weekly Loop** — Escalated topics injected into Weekly Pulse generator as "High-Frequency Support Issues" section. | 4 | Escalated topics appear in generated pulse. Empirical frequency data included. |
| 4.4 | **Live Synchronization Verification** — Approving an explainer in the Weekly Loop immediately updates Response Loop behavior without system restart. | 4 | End-to-end test: approve explainer → subsequent matching query receives canonical answer without restart. |
| 4.5 | **Phase 4 Tests** — `tests/test_phase4.py` passes: canonical reuse verified, ≥5/week escalation verified. | 4 | `pytest tests/test_phase4.py` exits cleanly with all assertions passing. |

**Phase 4 Total: /20**

---

## 7. Phase 5: HITL Web Application & API Gateway

**Weight: 15%**
**Objective:** Build the interactive web application with role-specific workflows for Support Specialists, Product Managers, and Compliance Auditors.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 5.1 | **FastAPI Backend — Support Endpoints** — REST endpoints for: fetch ticket queue, inspect agent deliberations, edit draft, approve & dispatch, reject. Every mutating action wrapped in State Diff Engine. | 4 | API endpoints respond correctly. Mutation diffs captured and validated for atomic single-entity scope. |
| 5.2 | **FastAPI Backend — Product Endpoints** — REST endpoints for: fetch weekly pulse, inspect themes/quotes, review and approve canonical explainers. | 4 | Pulse and explainer data served correctly. Approval commits to canonical store. |
| 5.3 | **FastAPI Backend — Audit Endpoints** — REST endpoints for audit log retrieval and state diff inspection. | 4 | Audit history queryable by entity type, entity ID, and time range. |
| 5.4 | **Support Queue UI** — Ticket list with status badges (`PENDING_APPROVAL`, `APPROVED`, `EDITED`, `REJECTED`, `NOT_COVERED`). Detailed inspection: original sanitized query, multi-agent evaluation cards, editable draft box. Live client-side validation (≤3 sentences, ≥1 source link). Internal routing note display. | 4 | UI renders queue correctly. Client-side validators prevent invalid approvals. Routing notes visible. |
| 5.5 | **Product Intelligence UI** — Weekly Pulse card with word-count meter (≤250w). Interactive quote cards linking to review IDs. Canonical Explainer card with 1-click "Approve into Canonical Store" button. | 4 | Pulse displays within word cap. Quotes link to source reviews. Approval button functions end-to-end. |
| 5.6 | **State Diff & Audit UI** — Visual before/after JSON diff viewer showing exact patch operations for every action. | 4 | Diff viewer correctly renders add/remove/replace operations with color coding. |
| 5.7 | **Design Quality & Polish** — Clean aesthetics, modern typography, responsive layout, accessible interactive elements. Dark mode / premium feel. | 4 | UI passes visual inspection for responsiveness, typography, and interaction quality. |
| 5.8 | **Phase 5 Tests** — `tests/test_phase5.py` verifies all API endpoints, HTTP status codes, mutation diff integrity, and client action workflows. | 4 | `pytest tests/test_phase5.py` exits cleanly with all assertions passing. |

**Phase 5 Total: /32**

---

## 8. Phase 6: End-to-End Verification, 15-Claim Audit & Deployment Readiness

**Weight: 10%**
**Objective:** Comprehensive system validation, 15-claim grounding audit, adversarial testing, and deployment packaging.

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| 6.1 | **15-Claim Grounding & Lineage Audit** — 15 distinct factual claims sampled across response drafts, weekly pulse summaries, and fee explainers. Each claim resolves to either an official Milestone 1 source URL or a verified `review_id`. | 4 | `scripts/verify_claims_audit.py` reports 15/15 claims passing strict source lineage. |
| 6.2 | **Adversarial PII Pen-Test** — Obfuscated PAN numbers (e.g., `A B C D E 1 2 3 4 F`), spaced phone numbers, and embedded demat IDs are all caught and redacted. | 4 | 100% sanitization across adversarial variations. Zero leakage in logs or state diffs. |
| 6.3 | **Adversarial Financial Advice Pen-Test** — Advisory prompts (e.g., *"Suggest best stocks for 2026"*, *"Will Nifty hit 30,000?"*) all refused deterministically. | 4 | 100% refusal rate. Standard refusal template used consistently. |
| 6.4 | **Full End-to-End Test Suite** — All test files pass cleanly: `tests/test_phase0.py` through `tests/test_phase5.py` + `tests/test_e2e.py`. Zero regressions. | 4 | `pytest tests/` exits with 0 failures and 0 errors. |
| 6.5 | **Deployment Packaging** — `Dockerfile` and/or `docker-compose.yml` present. Container builds and runs successfully. `README.md` with setup guide and operational runbook. | 4 | `docker build` succeeds. Container starts and serves the application. README covers prerequisites, setup, and usage. |

**Phase 6 Total: /20**

---

## 9. Cross-Cutting Evaluation Criteria

These criteria apply across all phases and are evaluated holistically:

| # | Criterion | Max Score | Evidence Required |
| :---: | :--- | :---: | :--- |
| X.1 | **Code Quality & Organization** — Clean project structure, consistent naming, type annotations, docstrings, modular design. No dead code or hardcoded secrets. | 4 | Code review passes for PEP 8 compliance, type hints, and documentation. |
| X.2 | **Error Handling & Resilience** — Graceful failure modes for missing corpus data, LLM unavailability, malformed inputs, and network timeouts. | 4 | Error paths tested. Appropriate HTTP status codes returned. No unhandled exceptions in common failure modes. |
| X.3 | **Deterministic Behavior** — All safety-critical operations (PII scrubbing, advice refusal, sentence caps, citation validation) are deterministic — no reliance on LLM judgment for safety enforcement. | 4 | Safety checks implemented as rule-based code, not LLM prompts. Consistent results across runs. |
| X.4 | **Data Lineage & Traceability** — Every generated output (draft, pulse, explainer) traces back to source inputs (corpus chunks, review IDs). Lineage is queryable. | 4 | Audit trail from output → intermediate agents → source data exists and is inspectable. |
| X.5 | **Human-in-the-Loop Integrity** — Zero autonomous external actions. Nothing dispatched to users, published, or finalized without explicit per-action human approval. | 4 | No code path sends a response or publishes an artifact without passing through HITL approval gate. |

**Cross-Cutting Total: /20**

---

## 10. Traceability Matrix: Success Criteria → Evaluation Mapping

| Success Criteria (from Problem Statement) | Phase(s) Evaluated | Evaluation Criteria IDs | Verification Script / Test |
| :--- | :---: | :--- | :--- |
| Every question answered or explained (≤3 sentences or explicit "not covered" with searched queries) | 2, 5 | 2.1, 2.4, 2.5, 2.6, 5.4 | `tests/test_phase2.py`, Reviewer Agent |
| Weekly loop runs unattended within caps (≤250w pulse, ≤6 bullets, ≤5 themes, quotes trace to review IDs) | 3 | 3.1–3.6 | `tests/test_phase3.py` |
| Edits and approvals stay contained (diff confirms only target item mutated) | 1, 5 | 1.5, 1.6, 1.7, 5.1, 5.6 | `tests/test_phase1.py`, `StateDiffEngine` |
| Grounded claims & zero sensitive leaks (15-claim audit, 100% PII/advice refusal) | 1, 6 | 1.1–1.4, 6.1–6.3 | `scripts/verify_claims_audit.py`, `scripts/adversarial_security_test.py` |
| Bi-directional connection (canonical explainer reuse, ≥5×/wk escalation) | 4 | 4.1–4.5 | `tests/test_phase4.py` |

---

## 11. Scoring Summary Template

| Phase | Phase Title | Weight | Score | Max | Weighted % |
| :---: | :--- | :---: | :---: | :---: | :---: |
| 0 | Foundations & Corpus Setup | 15% | — | 24 | — |
| 1 | Safety, Privacy & State Isolation | 15% | — | 32 | — |
| 2 | Response Loop Pipeline | 20% | — | 28 | — |
| 3 | Weekly Loop Pipeline | 15% | — | 24 | — |
| 4 | Bi-Directional Bridge | 10% | — | 20 | — |
| 5 | HITL Web Application & API Gateway | 15% | — | 32 | — |
| 6 | E2E Audit & Deployment | 10% | — | 20 | — |
| **X** | **Cross-Cutting Criteria** | — | — | 20 | — |
| | **TOTAL** | **100%** | — | **200** | — |

### Grade Bands

| Grade | Weighted Score Range | Interpretation |
| :---: | :---: | :--- |
| **A** | 90–100% | Production-ready. All success criteria met with robust testing and polish. |
| **B** | 75–89% | Feature-complete. Minor gaps in edge-case handling or UI polish. |
| **C** | 60–74% | Functional core but significant gaps in testing, security, or integration. |
| **D** | 40–59% | Partial implementation. Multiple phases incomplete or undertested. |
| **F** | <40% | Insufficient. Major subsystems missing or non-functional. |

---

## 12. Evaluation Checklist (Quick Reference)

### Phase 0 — Foundations
- [ ] Project skeleton with correct dependencies
- [ ] Pydantic models with field validations
- [ ] Milestone 1 corpus indexed with metadata
- [ ] Hybrid search returns grounded results
- [ ] All Phase 0 tests pass

### Phase 1 — Security & State Isolation
- [ ] 100% PII redaction (PAN, Phone, Aadhaar, Account, Email)
- [ ] Entity-based name/location masking
- [ ] Zero unredacted PII in storage/logs
- [ ] 100% SEBI advice refusal
- [ ] State capture with SHA-256 hashing
- [ ] RFC 6902 JSON patch diffs
- [ ] Cross-entity mutation blocked (`StateIsolationError`)
- [ ] Append-only audit log
- [ ] All Phase 1 tests pass

### Phase 2 — Response Loop
- [ ] Agent 1: Hybrid search with τ_rel = 0.72
- [ ] Agent 2: Compliance guard blocks advisory content
- [ ] Agent 3: Synthesis with routing note (category, urgency, sentiment, reason)
- [ ] Orchestrator: Parallel execution + fallback
- [ ] Reviewer: ≤3 sentences, 1 source URL, zero PII
- [ ] End-to-end pipeline functional
- [ ] All Phase 2 tests pass

### Phase 3 — Weekly Loop
- [ ] Review ingestion with date windowing and PII scrubbing
- [ ] Clustering ≤5 themes, top 3 isolated, fee friction extracted
- [ ] Weekly Pulse ≤250 words, 2–3 quotes with review IDs, 3 action ideas
- [ ] Fee Explainer ≤6 bullets, ≥2 source links, ISO-8601 date
- [ ] Unattended execution (no manual intervention)
- [ ] All Phase 3 tests pass

### Phase 4 — Bi-Directional Bridge
- [ ] Canonical store with embedding-based fast-path (similarity >0.88)
- [ ] 7-day sliding window frequency tracker
- [ ] Escalation at ≥5 occurrences/week
- [ ] Live sync without restart
- [ ] All Phase 4 tests pass

### Phase 5 — Web Application
- [ ] Support queue with status badges and agent deliberation cards
- [ ] Live client-side validation (≤3 sentences, ≥1 link)
- [ ] Product pulse dashboard with word-count meter
- [ ] 1-click canonical explainer approval
- [ ] JSON diff audit viewer
- [ ] Modern, responsive, polished UI
- [ ] All Phase 5 tests pass

### Phase 6 — E2E Audit & Deployment
- [ ] 15/15 claims pass source lineage audit
- [ ] 100% adversarial PII redaction
- [ ] 100% adversarial advice refusal
- [ ] Full test suite passes (zero failures)
- [ ] Docker build succeeds; container runs
- [ ] README with setup guide

### Cross-Cutting
- [ ] Clean code structure with type hints and docstrings
- [ ] Graceful error handling
- [ ] Deterministic safety enforcement (no LLM-dependent safety)
- [ ] Full data lineage traceability
- [ ] Zero autonomous actions (HITL integrity)
