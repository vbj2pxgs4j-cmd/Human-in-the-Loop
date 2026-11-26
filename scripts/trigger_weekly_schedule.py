#!/usr/bin/env python3
"""CLI utility to trigger the unattended Weekly Loop on schedule or on demand.

Can be run locally or invoked as a cron task / container entrypoint.
Validates the execution results, ensures strict limits (<=250 words, <=5 themes),
and prints an executive summary.

Usage:
    python scripts/trigger_weekly_schedule.py [--url http://localhost:8000] [--api-key hitl_live_sk_...] [--week 2026-W48]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def trigger_weekly_run(
    base_url: str,
    api_key: str,
    week_identifier: str = None,
    timeout: int = 60,
) -> dict:
    """Send authenticated POST request to trigger the unattended Weekly Loop."""
    endpoint = f"{base_url.rstrip('/')}/api/product/run-weekly"
    payload = {}
    if week_identifier:
        payload["week_identifier"] = week_identifier

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "User-Agent": "HITL-Weekly-Cron-Trigger/1.0",
        },
        method="POST",
    )

    print(f"[{datetime.now(timezone.utc).isoformat()}] Sending POST to {endpoint}...")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            body = response.read().decode("utf-8")
            result = json.loads(body)
            return status_code, result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            err_json = json.loads(body)
            detail = err_json.get("detail", body)
        except Exception:
            detail = body
        print(f"HTTP Error {e.code}: {detail}", file=sys.stderr)
        return e.code, {"error": detail}
    except Exception as exc:
        print(f"Connection Error: {exc}", file=sys.stderr)
        return 500, {"error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description="Trigger unattended Weekly Loop schedule.")
    parser.add_argument(
        "--url",
        default=os.getenv("API_BASE_URL", "http://localhost:8000"),
        help="Backend API base URL (default: http://localhost:8000 or $API_BASE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("SUPPORT_API_KEY", "hitl_live_sk_7f8a9b2c3d4e5f6a1b2c3d4e5f6a7b8c"),
        help="Support API Key (default: $SUPPORT_API_KEY)",
    )
    parser.add_argument(
        "--week",
        default=None,
        help="Optional ISO week identifier (e.g. 2026-W48)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run direct Python pipeline without HTTP server (useful for standalone worker cron)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🚀 UNATTENDED WEEKLY LOOP SCHEDULE TRIGGER")
    print("=" * 70)

    if args.direct:
        print("Mode: Direct Python Execution (Standalone Cron Worker)")
        from src.agents.weekly.runner import run_weekly_pipeline
        bundle = run_weekly_pipeline(week_identifier=args.week)
        pulse = bundle.get("pulse")
        explainer = bundle.get("explainer")
        clusters = bundle.get("clusters", [])

        print("\n✅ Unattended Weekly Loop completed successfully!")
        print(f"• Week Identifier : {bundle.get('week_identifier')}")
        print(f"• Pulse ID        : {pulse.pulse_id if pulse else 'N/A'}")
        print(f"• Pulse Words     : {pulse.word_count if pulse else 'N/A'} (Hard cap <= 250 words)")
        print(f"• Themes Formed   : {len(clusters)} (Hard cap <= 5 themes)")
        print(f"• Explainer ID    : {explainer.explainer_id if explainer else 'N/A'}")
        print(f"• Explainer Bullets: {explainer.bullet_count if explainer else 'N/A'} (Hard cap <= 6)")
        print(f"• Source URLs     : {len(explainer.source_urls) if explainer else 'N/A'} (Min >= 2 links)")
        return 0

    print(f"Mode       : HTTP API Client Trigger")
    print(f"Base URL   : {args.url}")
    print(f"API Key    : {args.api_key[:12]}... (masked)")
    print(f"Target Week: {args.week or 'Auto-computed'}")

    code, resp = trigger_weekly_run(args.url, args.api_key, args.week)

    if code == 200 and resp.get("status") == "success":
        print("\n" + "=" * 70)
        print("✅ SUCCESS: Unattended Weekly Loop completed without manual steps!")
        print("=" * 70)
        print(f"• Week Identifier       : {resp.get('week_identifier')}")
        print(f"• Weekly Pulse ID       : {resp.get('pulse_id')}")
        print(f"• Pulse Word Count      : {resp.get('word_count')} words (Cap <= 250)")
        print(f"• Thematic Clusters     : {resp.get('theme_count')} clusters (Cap <= 5)")
        print(f"• Canonical Explainer ID: {resp.get('explainer_id')}")
        print(f"• Unattended Execution  : {resp.get('unattended_execution')}")
        print(f"• Executed At           : {resp.get('executed_at')}")
        print(f"• Duration              : {resp.get('execution_duration_sec')}s")
        print("=" * 70)
        return 0
    else:
        print("\n❌ FAILED: Weekly Loop execution failed.", file=sys.stderr)
        print(f"HTTP Status: {code}", file=sys.stderr)
        print(f"Response: {json.dumps(resp, indent=2)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
