"""Orchestrator: pull activity from configured sources, write activity.json + calendar.html."""
import argparse
import json
from datetime import datetime, time, timedelta, timezone
from importlib import resources
from pathlib import Path

from dotenv import load_dotenv

from . import drive as drive_source
from . import gcal as gcal_source
from . import github as github_source
from . import google_auth


def render_html(payload, out_dir: Path):
    template = resources.files(__package__).joinpath("calendar_template.html").read_text()
    data_json = json.dumps(payload).replace("</", "<\\/")
    (out_dir / "calendar.html").write_text(template.replace("__DATA_PLACEHOLDER__", data_json))


def parse_bound(s: str, *, end: bool) -> datetime:
    """Parse YYYY-MM-DD (date-only → 00:00 for start, 23:59:59.999999 for end) or ISO datetime."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
        t = time.max if end else time.min
        return datetime.combine(d, t, tzinfo=timezone.utc)
    except ValueError:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main():
    ap = argparse.ArgumentParser(prog="activity-tracker")
    ap.add_argument("--start", help="Start date YYYY-MM-DD or ISO datetime (default: 30 days before --end)")
    ap.add_argument("--end", help="End date YYYY-MM-DD or ISO datetime (default: now)")
    ap.add_argument("--skip-drive", action="store_true")
    ap.add_argument("--skip-gcal", action="store_true")
    ap.add_argument("--skip-github", action="store_true")
    args = ap.parse_args()

    cwd = Path.cwd()
    load_dotenv(cwd / ".env")
    until_dt = parse_bound(args.end, end=True) if args.end else datetime.now(timezone.utc)
    since_dt = parse_bound(args.start, end=False) if args.start else until_dt - timedelta(days=30)
    if since_dt >= until_dt:
        ap.error(f"--start ({since_dt.isoformat()}) must be before --end ({until_dt.isoformat()})")

    items = []
    user_email = ""

    needs_google = not (args.skip_drive and args.skip_gcal)
    creds = google_auth.get_creds(cwd) if needs_google else None

    if not args.skip_drive:
        user_email, drive_items = drive_source.fetch(creds, since_dt, until_dt)
        items.extend(drive_items)
    if not args.skip_gcal:
        items.extend(gcal_source.fetch(creds, since_dt, until_dt))
    if not args.skip_github:
        items.extend(github_source.fetch(since_dt, until_dt))

    payload = {
        "user_email": user_email,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "since": since_dt.isoformat(),
        "until": until_dt.isoformat(),
        "items": items,
    }
    (cwd / "activity.json").write_text(json.dumps(payload, indent=2))
    render_html(payload, cwd)

    by_kind = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    total_sessions = sum(len(i["sessions"]) for i in items)
    breakdown = ", ".join(f"{n} {k}" for k, n in sorted(by_kind.items()))
    print(f"\nWrote activity.json ({len(items)} items: {breakdown}; {total_sessions} sessions)")
    print("Open calendar.html in your browser.")


if __name__ == "__main__":
    main()
