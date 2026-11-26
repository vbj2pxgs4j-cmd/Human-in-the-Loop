"""Comprehensive test suite for Phase 5: HITL Web Application & API Gateway.

Validates:
1. Criterion 5.1: FastAPI Backend — Support Endpoints (queue, deliberation, edit, approve, reject).
2. Criterion 5.2: FastAPI Backend — Product Endpoints (pulse <= 250w, quotes with review IDs, explainers).
3. Criterion 5.3: FastAPI Backend — Audit Endpoints (diff inspection, filtering).
4. Edge Case EC-HITL-01: Human Edit Validation Gate (<= 3 sentences, whitelisted URL enforcement).
5. Edge Case EC-HITL-02: Concurrent Operator Approvals (HTTP 409 Conflict on stale pre_state_hash).
6. Edge Case EC-HITL-03: State Mutation Boundary Breach (strict single-entity containment).
7. Static UI asset serving and health checks.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.bridge.canonical_store import get_canonical_store
from src.models.ticket import TicketStatus
from src.storage.audit_logger import get_audit_logger
from src.storage.product_store import get_product_store
from src.storage.state_diff_engine import capture_state
from src.storage.ticket_store import get_ticket_store


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create test client for FastAPI gateway."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_stores():
    """Ensure clean stores for each test run."""
    ticket_store = get_ticket_store()
    ticket_store._tickets.clear()
    ticket_store._seed_default_tickets()

    product_store = get_product_store()
    if not product_store._latest_pulse:
        product_store._seed_default_data()

    yield


# ==============================================================================
# 1. Support Queue Endpoints (Criterion 5.1)
# ==============================================================================

class TestSupportEndpoints:
    """Tests for Support Queue endpoints."""

    def test_list_tickets(self, client: TestClient):
        """GET /api/support/tickets must return ticket list with proper schema."""
        resp = client.get("/api/support/tickets")
        assert resp.status_code == 200
        tickets = resp.json()
        assert len(tickets) >= 4
        assert any(t["ticket_id"] == "tkt_10291" for t in tickets)

    def test_list_tickets_filtered_by_status(self, client: TestClient):
        """GET /api/support/tickets?status=PENDING_APPROVAL must filter properly."""
        resp = client.get("/api/support/tickets?status=PENDING_APPROVAL")
        assert resp.status_code == 200
        tickets = resp.json()
        assert len(tickets) > 0
        for t in tickets:
            assert t["status"] == "PENDING_APPROVAL"

    def test_get_ticket_details(self, client: TestClient):
        """GET /api/support/tickets/{id} returns ticket details with deliberation."""
        resp = client.get("/api/support/tickets/tkt_10291")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket_id"] == "tkt_10291"
        assert "deliberation" in data
        assert "routing_note" in data
        assert data["routing_note"]["category"] == "DP_CHARGES"

    def test_get_ticket_not_found(self, client: TestClient):
        """GET /api/support/tickets/invalid_id returns 404."""
        resp = client.get("/api/support/tickets/non_existent_9999")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_submit_new_inquiry(self, client: TestClient):
        """POST /api/support/inquiries processes inquiry and inserts ticket into queue."""
        payload = {
            "raw_query": "Why was DP charge of Rs. 15.93 debited on selling shares? [REDACTED_PHONE]",
            "customer_id": "cust_test_user",
        }
        resp = client.post("/api/support/inquiries", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert "ticket_id" in data
        assert data["sentence_count"] <= 3
        assert data["status"] in ("PENDING_APPROVAL", "APPROVED")

        # Confirm ticket exists in store
        store_ticket = get_ticket_store().get_ticket(data["ticket_id"])
        assert store_ticket is not None

    def test_edit_draft_valid(self, client: TestClient):
        """PUT /api/support/tickets/{id}/edit updates draft and logs mutation."""
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]

        payload = {
            "proposed_draft": "DP charges of Rs. 15.93 apply when selling equity shares. Source: https://cdslindia.com/charges",
            "pre_state_hash": pre_hash,
            "operator_id": "operator_test",
        }
        resp = client.put("/api/support/tickets/tkt_10291/edit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "EDITED"
        assert data["operator_id"] == "operator_test"
        assert "https://cdslindia.com/charges" in data["proposed_draft"]

        # Verify mutation was recorded in audit log
        logs = get_audit_logger().get_audit_history("tkt_10291")
        assert len(logs) > 0
        assert logs[-1].action == "EDIT_DRAFT"

    def test_approve_ticket_success(self, client: TestClient):
        """POST /api/support/tickets/{id}/approve approves draft and records resolution."""
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]

        payload = {
            "pre_state_hash": pre_hash,
            "operator_id": "operator_approver",
        }
        resp = client.post("/api/support/tickets/tkt_10291/approve", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "APPROVED"
        assert data["resolved_at"] is not None
        assert data["operator_id"] == "operator_approver"

    def test_reject_ticket_success(self, client: TestClient):
        """POST /api/support/tickets/{id}/reject rejects draft."""
        ticket = get_ticket_store().get_ticket("tkt_10292")
        pre_hash = capture_state(ticket)["hash"]

        payload = {
            "pre_state_hash": pre_hash,
            "operator_id": "operator_rejector",
            "reason": "Draft needs re-evaluation",
        }
        resp = client.post("/api/support/tickets/tkt_10292/reject", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "REJECTED"


# ==============================================================================
# 2. Product Intelligence Endpoints (Criterion 5.2)
# ==============================================================================

class TestProductEndpoints:
    """Tests for Product Intelligence endpoints."""

    def test_get_weekly_pulse(self, client: TestClient):
        """GET /api/product/pulse returns pulse with <= 250 words and supporting quotes."""
        resp = client.get("/api/product/pulse")
        assert resp.status_code == 200
        data = resp.json()
        assert data["word_count"] <= 250
        assert len(data["supporting_quotes"]) >= 2
        for q in data["supporting_quotes"]:
            assert "Review #" in q or "rev_" in q
        assert len(data["action_ideas"]) == 3

    def test_list_themes(self, client: TestClient):
        """GET /api/product/themes returns theme clusters with quote lineage."""
        resp = client.get("/api/product/themes")
        assert resp.status_code == 200
        themes = resp.json()
        assert len(themes) > 0
        assert len(themes) <= 5
        for th in themes:
            assert "theme_title" in th
            assert "review_ids" in th
            assert len(th["review_ids"]) > 0

    def test_list_explainers(self, client: TestClient):
        """GET /api/product/explainers lists canonical fee explainers."""
        resp = client.get("/api/product/explainers")
        assert resp.status_code == 200
        explainers = resp.json()
        assert len(explainers) >= 2
        for exp in explainers:
            assert exp["bullet_count"] <= 6
            assert len(exp["source_urls"]) >= 2

    def test_approve_explainer_into_canonical_store(self, client: TestClient):
        """POST /api/product/explainers/{id}/approve approves draft explainer."""
        canonical_store = get_canonical_store()
        exp = canonical_store.get_explainer("expl_amc_charges")
        assert exp is not None

        resp = client.post(
            "/api/product/explainers/expl_amc_charges/approve",
            json={"approved_by": "product_lead_test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "APPROVED"
        assert data["approved_by"] == "product_lead_test"

        # Verify updated in canonical store
        updated = canonical_store.get_explainer("expl_amc_charges")
        assert updated.status == "APPROVED"

    def test_invalidate_explainer(self, client: TestClient):
        """POST /api/product/explainers/{id}/invalidate archives an explainer (EC-BRID-01)."""
        resp = client.post(
            "/api/product/explainers/expl_dp_charges/invalidate",
            json={"operator_id": "compliance_lead"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ARCHIVED"

        # Verify in store
        store_exp = get_canonical_store().get_explainer("expl_dp_charges")
        assert store_exp.status == "ARCHIVED"

    def test_trigger_weekly_run(self, client: TestClient):
        """POST /api/product/pulse/run executes unattended weekly pipeline."""
        resp = client.post("/api/product/pulse/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["unattended_execution"] is True
        assert data["word_count"] <= 250


# ==============================================================================
# 3. Audit & State Diff Endpoints (Criterion 5.3)
# ==============================================================================

class TestAuditEndpoints:
    """Tests for Audit and State Diff inspection endpoints."""

    def test_list_audit_logs(self, client: TestClient):
        """GET /api/audit/logs returns chronological mutation logs."""
        resp = client.get("/api/audit/logs")
        assert resp.status_code == 200
        logs = resp.json()
        assert isinstance(logs, list)

    def test_filter_audit_logs_by_entity_type(self, client: TestClient):
        """GET /api/audit/logs?entity_type=ticket filters logs."""
        resp = client.get("/api/audit/logs?entity_type=ticket")
        assert resp.status_code == 200
        logs = resp.json()
        for log in logs:
            assert log["entity_type"].lower() == "ticket"

    def test_get_audit_diff_details(self, client: TestClient):
        """GET /api/audit/diff/{audit_id} returns RFC 6902 patch operations."""
        # Ensure at least one mutation exists
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]
        client.put(
            "/api/support/tickets/tkt_10291/edit",
            json={
                "proposed_draft": "Updated draft with valid link. Source: https://cdslindia.com/charges",
                "pre_state_hash": pre_hash,
            },
        )

        logs = client.get("/api/audit/logs?entity_id=tkt_10291").json()
        assert len(logs) > 0
        latest_audit_id = logs[0]["audit_id"]

        diff_resp = client.get(f"/api/audit/diff/{latest_audit_id}")
        assert diff_resp.status_code == 200
        diff_data = diff_resp.json()
        assert "pre_state_hash" in diff_data
        assert "post_state_hash" in diff_data
        assert "patch_operations" in diff_data
        assert diff_data["is_isolated"] is True


# ==============================================================================
# 4. Edge Cases: EC-HITL-01, EC-HITL-02, EC-HITL-03
# ==============================================================================

class TestEdgeCasesHITL:
    """Rigorous validation of HITL edge cases."""

    def test_human_edit_validation_gate_sentence_overflow(self, client: TestClient):
        """EC-HITL-01: Server blocks edits exceeding hard cap of 3 sentences with HTTP 422."""
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]

        # 5-sentence draft violating length cap
        invalid_5_sentence_draft = (
            "This is the first sentence about charges. "
            "Here is the second sentence explaining depository debits. "
            "This is the third sentence regarding equity sales. "
            "And here is the fourth sentence which exceeds the maximum allowed limit. "
            "Finally, this fifth sentence makes it completely invalid. Source: https://cdslindia.com/charges"
        )

        resp = client.put(
            "/api/support/tickets/tkt_10291/edit",
            json={"proposed_draft": invalid_5_sentence_draft, "pre_state_hash": pre_hash},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"].lower()
        assert "violates sentence limit" in detail or "max 3 sentences" in detail

    def test_human_edit_validation_gate_missing_source_link(self, client: TestClient):
        """EC-HITL-01: Server blocks edits lacking an official whitelisted source link with HTTP 422."""
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]

        # Valid sentence length (2 sentences) but completely lacking a citation URL
        draft_without_link = (
            "Depository Participant charges are debited flat when selling shares. "
            "This applies per company irrespective of the quantity sold."
        )

        resp = client.put(
            "/api/support/tickets/tkt_10291/edit",
            json={"proposed_draft": draft_without_link, "pre_state_hash": pre_hash},
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"].lower()
        assert "source link" in detail

    def test_human_edit_validation_gate_non_whitelisted_link(self, client: TestClient):
        """EC-HITL-01: Server blocks edits citing untrusted / non-whitelisted domains with HTTP 422."""
        ticket = get_ticket_store().get_ticket("tkt_10291")
        pre_hash = capture_state(ticket)["hash"]

        draft_untrusted_domain = (
            "DP charges are debited per company per day. "
            "Source: https://random-unverified-blog.xyz/stock-fees"
        )

        resp = client.put(
            "/api/support/tickets/tkt_10291/edit",
            json={"proposed_draft": draft_untrusted_domain, "pre_state_hash": pre_hash},
        )
        assert resp.status_code == 422
        assert "source link" in resp.json()["detail"].lower()

    def test_concurrent_operator_conflict(self, client: TestClient):
        """EC-HITL-02: Simultaneous operator race condition returns HTTP 409 Conflict."""
        # Operator A and Operator B both inspect ticket tkt_10291 with hash H1
        ticket = get_ticket_store().get_ticket("tkt_10291")
        initial_hash = capture_state(ticket)["hash"]

        # Operator A successfully approves the ticket, advancing state hash to H2
        resp_a = client.post(
            "/api/support/tickets/tkt_10291/approve",
            json={"pre_state_hash": initial_hash, "operator_id": "operator_a"},
        )
        assert resp_a.status_code == 200

        # Operator B submits an action moments later with the stale initial_hash H1
        resp_b = client.post(
            "/api/support/tickets/tkt_10291/reject",
            json={"pre_state_hash": initial_hash, "operator_id": "operator_b"},
        )
        assert resp_b.status_code == 409
        assert "already been updated" in resp_b.json()["detail"].lower()

    def test_state_diff_isolation_assertion(self, client: TestClient):
        """EC-HITL-03: Editing or approving ticket T1 mutates strictly T1 and leaves all other tickets untouched."""
        store = get_ticket_store()
        t1 = store.get_ticket("tkt_10291")
        t2 = store.get_ticket("tkt_10292")

        t1_pre_hash = capture_state(t1)["hash"]
        t2_pre_hash = capture_state(t2)["hash"]

        # Mutate T1
        client.put(
            "/api/support/tickets/tkt_10291/edit",
            json={
                "proposed_draft": "Updated T1 draft. Source: https://cdslindia.com/charges",
                "pre_state_hash": t1_pre_hash,
                "operator_id": "operator_isolation_test",
            },
        )

        t1_post = store.get_ticket("tkt_10291")
        t2_post = store.get_ticket("tkt_10292")

        # T1 must have mutated
        assert capture_state(t1_post)["hash"] != t1_pre_hash

        # T2 MUST BE 100% UNTOUCHED (Identical SHA-256 hash)
        assert capture_state(t2_post)["hash"] == t2_pre_hash


# ==============================================================================
# 5. Static Assets & Gateway Health
# ==============================================================================

class TestStaticServingAndHealth:
    """Tests for static web UI serving and health endpoints."""

    def test_health_endpoint(self, client: TestClient):
        """GET /api/health returns healthy status."""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "cors_origins" in data

    def test_serve_index_html(self, client: TestClient):
        """GET / serves the single-page application index.html."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Investment Assistant" in resp.text
        assert "Support Queue" in resp.text
        assert "Product Intelligence" in resp.text

    def test_serve_static_css(self, client: TestClient):
        """GET /static/css/style.css serves valid CSS styling."""
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200
        assert "--bg-primary" in resp.text

    def test_serve_static_js(self, client: TestClient):
        """GET /static/js/app.js serves JavaScript controller."""
        resp = client.get("/static/js/app.js")
        assert resp.status_code == 200
        assert "validateDraftLive" in resp.text
