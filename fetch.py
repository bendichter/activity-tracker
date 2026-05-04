#!/usr/bin/env python3
"""Orchestrator: pull activity from configured sources, write activity.json + calendar.html."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from sources import drive as drive_source
from sources import gcal as gcal_source
from sources import github as github_source
from sources import google_auth

ROOT = Path(__file__).parent


def render_html(payload):
    template = (ROOT / "calendar_template.html").read_text()
    data_json = json.dumps(payload).replace("</", "<\\/")
    (ROOT / "calendar.html").write_text(template.replace("__DATA_PLACEHOLDER__", data_json))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Look back this many days (default: 30)")
    ap.add_argument("--skip-drive", action="store_true")
    ap.add_argument("--skip-gcal", action="store_true")
    ap.add_argument("--skip-github", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)

    items = []
    user_email = ""

    needs_google = not (args.skip_drive and args.skip_gcal)
    creds = google_auth.get_creds(ROOT) if needs_google else None

    if not args.skip_drive:
        user_email, drive_items = drive_source.fetch(creds, since_dt)
        items.extend(drive_items)
    if not args.skip_gcal:
        items.extend(gcal_source.fetch(creds, since_dt))
    if not args.skip_github:
        items.extend(github_source.fetch(ROOT, since_dt))

    payload = {
        "user_email": user_email,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "since": since_dt.isoformat(),
        "days": args.days,
        "items": items,
    }
    (ROOT / "activity.json").write_text(json.dumps(payload, indent=2))
    render_html(payload)

    by_kind = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    total_sessions = sum(len(i["sessions"]) for i in items)
    breakdown = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
    print(f"\nWrote activity.json ({len(items)} items: {breakdown}; {total_sessions} sessions)")
    print("Open calendar.html in your browser.")


if __name__ == "__main__":
    main()
