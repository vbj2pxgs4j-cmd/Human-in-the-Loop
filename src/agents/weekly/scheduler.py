"""In-app asynchronous background scheduler for the unattended Weekly Loop.

Runs periodically within the FastAPI application lifecycle, ensuring weekly intelligence
cycles execute unattended on a continuous schedule without manual intervention.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from src.config import Settings, get_settings
from src.models.explainer import CanonicalExplainer
from src.models.review import WeeklyPulse
from src.storage.audit_logger import get_audit_logger
from src.storage.product_store import get_product_store
from src.storage.state_diff_engine import capture_state

logger = logging.getLogger(__name__)


class WeeklyScheduler:
    """Manages scheduled background execution of the unattended Weekly Loop pipeline."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval_seconds = max(1, self.settings.WEEKLY_LOOP_INTERVAL_SECONDS)
        self._total_runs = 0
        self._last_run_timestamp: Optional[str] = None
        self._last_run_status: Optional[str] = None
        self._last_run_duration_sec: Optional[float] = None
        self._last_run_source: Optional[str] = None
        self._last_run_summary: Optional[Dict[str, Any]] = None
        self._next_run_timestamp: Optional[str] = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Return True if background scheduler task is currently active."""
        return self._running and (self._task is not None and not self._task.done())

    async def start(self) -> None:
        """Start the background scheduler task."""
        if self.is_running:
            logger.info("WeeklyScheduler is already running.")
            return

        self._running = True
        now = datetime.now(timezone.utc)
        next_run = now + timedelta(seconds=self._interval_seconds)
        self._next_run_timestamp = next_run.isoformat()

        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run_loop(), name="weekly-scheduler-loop")
        logger.info(
            "WeeklyScheduler started. Interval=%ds (%.1f hours). Next scheduled run: %s",
            self._interval_seconds,
            self._interval_seconds / 3600.0,
            self._next_run_timestamp,
        )

    async def stop(self) -> None:
        """Gracefully stop background scheduler task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("WeeklyScheduler stopped.")

    async def trigger_cycle_now(
        self,
        week_identifier: Optional[str] = None,
        source: str = "manual_api",
    ) -> Dict[str, Any]:
        """Execute one complete Weekly Loop cycle immediately without manual intervention.

        Thread-safe execution under asyncio.Lock ensuring no concurrent duplicate runs.
        """
        async with self._lock:
            start_time = datetime.now(timezone.utc)
            t0 = start_time.timestamp()
            logger.info("Executing unattended Weekly Loop cycle (source=%s, week=%s)...", source, week_identifier)

            try:
                # Execute unattended pipeline via ProductStore
                store = get_product_store()
                # Run CPU-bound / model pipeline in executor or direct invocation
                loop = asyncio.get_running_loop()
                bundle = await loop.run_in_executor(None, store.run_fresh_cycle, week_identifier)

                duration = datetime.now(timezone.utc).timestamp() - t0
                pulse: Optional[WeeklyPulse] = bundle.get("pulse")
                explainer: Optional[CanonicalExplainer] = bundle.get("explainer")

                self._total_runs += 1
                self._last_run_timestamp = start_time.isoformat()
                self._last_run_status = "success"
                self._last_run_duration_sec = round(duration, 3)
                self._last_run_source = source

                summary = {
                    "week_identifier": bundle.get("week_identifier"),
                    "pulse_id": pulse.pulse_id if pulse else None,
                    "pulse_word_count": pulse.word_count if pulse else 0,
                    "theme_count": len(bundle.get("clusters", [])),
                    "explainer_id": explainer.explainer_id if explainer else None,
                    "explainer_bullets": explainer.bullet_count if explainer else 0,
                    "source_urls_count": len(explainer.source_urls) if explainer else 0,
                    "unattended_execution": True,
                    "duration_seconds": round(duration, 3),
                }
                self._last_run_summary = summary

                now = datetime.now(timezone.utc)
                self._next_run_timestamp = (now + timedelta(seconds=self._interval_seconds)).isoformat()

                # Audit log mutation of weekly pulse
                if pulse:
                    try:
                        audit_logger = get_audit_logger()
                        pulse_snap = capture_state(pulse)
                        audit_logger.log_mutation(
                            operator_id=f"scheduler_{source}",
                            entity_type="weeklypulse",
                            entity_id=pulse.pulse_id,
                            action="SCHEDULED_WEEKLY_RUN",
                            pre_snapshot=pulse_snap,
                            post_snapshot=pulse_snap,
                        )
                    except Exception as audit_err:
                        logger.warning("Audit log recording failed for weekly run: %s", audit_err)

                logger.info(
                    "Weekly Loop cycle completed successfully: pulse=%s (%d words), themes=%d, explainer=%s (%.2fs)",
                    summary["pulse_id"],
                    summary["pulse_word_count"],
                    summary["theme_count"],
                    summary["explainer_id"],
                    duration,
                )

                return {
                    "status": "success",
                    "week_identifier": bundle.get("week_identifier"),
                    "pulse_id": pulse.pulse_id if pulse else None,
                    "word_count": pulse.word_count if pulse else None,
                    "theme_count": len(bundle.get("clusters", [])),
                    "explainer_id": explainer.explainer_id if explainer else None,
                    "unattended_execution": True,
                    "executed_at": start_time.isoformat(),
                    "execution_duration_sec": round(duration, 3),
                    "source": source,
                }

            except Exception as exc:
                duration = datetime.now(timezone.utc).timestamp() - t0
                self._last_run_timestamp = start_time.isoformat()
                self._last_run_status = "error"
                self._last_run_duration_sec = round(duration, 3)
                self._last_run_source = source
                self._last_run_summary = {"error": str(exc)}
                logger.error("Weekly Loop execution encountered an error: %s", exc, exc_info=True)
                raise exc

    def get_status(self) -> Dict[str, Any]:
        """Return diagnostic status and metrics of the weekly scheduler."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "scheduler_enabled": self.settings.ENABLE_IN_APP_SCHEDULER,
            "is_running": self.is_running,
            "interval_seconds": self._interval_seconds,
            "interval_hours": round(self._interval_seconds / 3600.0, 2),
            "total_runs": self._total_runs,
            "last_run_timestamp": self._last_run_timestamp,
            "last_run_status": self._last_run_status,
            "last_run_duration_sec": self._last_run_duration_sec,
            "last_run_source": self._last_run_source,
            "last_run_summary": self._last_run_summary,
            "next_run_timestamp": self._next_run_timestamp,
            "current_time": now,
        }

    async def _run_loop(self) -> None:
        """Internal asynchronous worker loop sleeping interval between scheduled executions."""
        logger.info("WeeklyScheduler worker loop initialized.")
        try:
            while self._running:
                logger.debug("WeeklyScheduler sleeping for %d seconds...", self._interval_seconds)
                await asyncio.sleep(self._interval_seconds)
                if not self._running:
                    break

                try:
                    logger.info("WeeklyScheduler timer triggered unattended execution.")
                    await self.trigger_cycle_now(source="scheduled_in_app")
                except Exception as loop_err:
                    logger.error("Error in scheduled Weekly Loop run: %s", loop_err, exc_info=True)
        except asyncio.CancelledError:
            logger.info("WeeklyScheduler worker loop cancelled.")
        finally:
            self._running = False


# Global singleton instance
_weekly_scheduler_instance: Optional[WeeklyScheduler] = None


def get_weekly_scheduler(settings: Optional[Settings] = None) -> WeeklyScheduler:
    """Retrieve global singleton WeeklyScheduler instance."""
    global _weekly_scheduler_instance
    if _weekly_scheduler_instance is None:
        _weekly_scheduler_instance = WeeklyScheduler(settings=settings)
    return _weekly_scheduler_instance
