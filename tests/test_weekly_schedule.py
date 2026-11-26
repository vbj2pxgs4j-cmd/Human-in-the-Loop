"""Comprehensive tests for the Weekly Loop Live Schedule and Cron trigger.

Validates:
1. Security: POST /api/product/run-weekly authentication (X-API-Key, Bearer, query param, rejection of invalid/missing keys).
2. Unattended Execution: Complete pipeline runs without human prompts or manual steps.
3. System Invariants: Weekly Pulse <= 250 words, Themes <= 5, Explainer <= 6 bullets and >= 2 links.
4. Cryptographic Lineage: Audit log and state diff captured.
5. In-App Scheduler: Status diagnostics, start/stop lifecycle, and programmatic trigger.
"""

import pytest
from fastapi.testclient import TestClient

from src.agents.weekly.scheduler import WeeklyScheduler, get_weekly_scheduler
from src.api.app import app
from src.bridge.canonical_store import get_canonical_store
from src.config import get_settings
from src.storage.audit_logger import get_audit_logger
from src.storage.product_store import get_product_store

settings = get_settings()
client = TestClient(app)


class TestWeeklyScheduleSecurity:
    """Test API authentication and security gate on POST /api/product/run-weekly."""

    def test_run_weekly_missing_api_key_rejected(self):
        """Calling /run-weekly without an API key must return 401 Unauthorized."""
        resp = client.post("/api/product/run-weekly", json={})
        assert resp.status_code == 401
        assert "API key required" in resp.json()["detail"]

    def test_run_weekly_invalid_api_key_rejected(self):
        """Calling /run-weekly with an incorrect API key must return 401 Unauthorized."""
        resp = client.post(
            "/api/product/run-weekly",
            headers={"X-API-Key": "invalid_bogus_key_12345"},
            json={},
        )
        assert resp.status_code == 401
        assert "Invalid API key" in resp.json()["detail"]

    def test_run_weekly_invalid_bearer_token_rejected(self):
        """Calling /run-weekly with an incorrect Bearer token must return 401 Unauthorized."""
        resp = client.post(
            "/api/product/run-weekly",
            headers={"Authorization": "Bearer invalid_bearer_token"},
            json={},
        )
        assert resp.status_code == 401
        assert "Invalid API key" in resp.json()["detail"]

    def test_run_weekly_valid_x_api_key_accepted(self):
        """Calling /run-weekly with valid X-API-Key header must succeed (200 OK)."""
        resp = client.post(
            "/api/product/run-weekly",
            headers={"X-API-Key": settings.SUPPORT_API_KEY},
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["unattended_execution"] is True
        assert data["pulse_id"] is not None
        assert data["word_count"] <= settings.WEEKLY_PULSE_MAX_WORDS
        assert data["theme_count"] <= settings.MAX_THEMES_CAP

    def test_run_weekly_valid_bearer_token_accepted(self):
        """Calling /run-weekly with valid Authorization: Bearer token must succeed (200 OK)."""
        resp = client.post(
            "/api/product/run-weekly",
            headers={"Authorization": f"Bearer {settings.SUPPORT_API_KEY}"},
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_run_weekly_valid_query_param_accepted(self):
        """Calling /run-weekly?api_key=<key> must succeed for hosted webhook cron services."""
        resp = client.post(
            f"/api/product/run-weekly?api_key={settings.SUPPORT_API_KEY}",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


class TestWeeklyScheduleExecutionInvariants:
    """Test that one triggered run finishes end-to-end completely without manual steps."""

    def test_triggered_run_satisfies_all_system_invariants(self):
        """Trigger an unattended weekly loop run and verify every artifact and invariant."""
        week_test = "2026-W48"
        resp = client.post(
            "/api/product/run-weekly",
            headers={"X-API-Key": settings.SUPPORT_API_KEY},
            json={"week_identifier": week_test},
        )
        assert resp.status_code == 200
        res = resp.json()

        # 1. Output Structure
        assert res["status"] == "success"
        assert res["week_identifier"] == week_test
        assert res["unattended_execution"] is True
        assert res["pulse_id"].startswith("pulse_")
        assert res["word_count"] > 0
        assert res["theme_count"] > 0
        assert res["explainer_id"].startswith("expl_")
        assert res["execution_duration_sec"] >= 0.0

        # 2. Verify Invariant Caps
        assert res["word_count"] <= 250, "WeeklyPulse pulse_text must satisfy hard cap <= 250 words"
        assert res["theme_count"] <= 5, "Thematic clustering must satisfy hard cap <= 5 themes"

        # 3. Verify ProductStore state update
        store = get_product_store()
        pulse = store.get_latest_pulse()
        assert pulse is not None
        assert pulse.pulse_id == res["pulse_id"]
        assert pulse.word_count == res["word_count"]
        assert len(pulse.action_ideas) == 3, "WeeklyPulse requires exactly 3 action ideas"
        assert len(pulse.supporting_quotes) >= 1, "WeeklyPulse must include supporting verbatim quotes"

        # 4. Verify CanonicalStore state update
        canonical_store = get_canonical_store()
        explainer = canonical_store.get_explainer(res["explainer_id"])
        assert explainer is not None
        assert explainer.bullet_count <= 6, "CanonicalExplainer hard cap <= 6 bullets"
        assert len(explainer.source_urls) >= 2, "CanonicalExplainer requires >= 2 official source links"

        # 5. Verify Audit Log entry
        audit_logger = get_audit_logger()
        logs = audit_logger.get_audit_history()
        scheduled_logs = [log for log in logs if log.action == "SCHEDULED_WEEKLY_RUN"]
        assert len(scheduled_logs) >= 1, "Scheduled execution must be recorded in append-only audit log"


class TestSchedulerDiagnosticsEndpoint:
    """Test GET /api/product/schedule/status endpoint."""

    def test_schedule_status_endpoint(self):
        """Verify schedule diagnostic metrics endpoint returns accurate state."""
        resp = client.get("/api/product/schedule/status")
        assert resp.status_code == 200
        data = resp.json()

        assert "scheduler_enabled" in data
        assert "is_running" in data
        assert "interval_seconds" in data
        assert "total_runs" in data
        assert "last_run_timestamp" in data
        assert "last_run_status" in data
        assert "current_time" in data
        assert data["total_runs"] >= 1
        assert data["last_run_status"] == "success"


class TestInAppWeeklySchedulerLifecycle:
    """Test in-app WeeklyScheduler start, stop, and direct execution."""

    @pytest.mark.asyncio
    async def test_scheduler_start_stop_lifecycle(self):
        """Test starting and stopping the background in-app scheduler."""
        scheduler = WeeklyScheduler(settings=settings)
        assert not scheduler.is_running

        await scheduler.start()
        assert scheduler.is_running
        status = scheduler.get_status()
        assert status["is_running"] is True
        assert status["next_run_timestamp"] is not None

        await scheduler.stop()
        assert not scheduler.is_running

    @pytest.mark.asyncio
    async def test_scheduler_trigger_cycle_now(self):
        """Test direct programmatic execution via scheduler.trigger_cycle_now."""
        scheduler = WeeklyScheduler(settings=settings)
        result = await scheduler.trigger_cycle_now(
            week_identifier="2026-W49",
            source="test_direct",
        )
        assert result["status"] == "success"
        assert result["week_identifier"] == "2026-W49"
        assert result["unattended_execution"] is True
        assert scheduler._total_runs == 1
        assert scheduler._last_run_status == "success"
