#!/usr/bin/env python3
"""Fetch Drive Activity for the signed-in user and render a week calendar.

Uses the Drive Activity API (granular per-edit timestamps, covers uploaded
Office files, PDFs, etc) instead of Drive's `revisions` endpoint.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/drive.activity.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

MIME_LABELS = {
    "application/vnd.google-apps.document": "Doc",
    "application/vnd.google-apps.spreadsheet": "Sheet",
    "application/vnd.google-apps.presentation": "Slides",
    "application/vnd.google-apps.drawing": "Drawing",
    "application/vnd.google-apps.form": "Form",
    "application/vnd.google-apps.script": "Script",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/msword": "Word",
    "application/vnd.ms-excel": "Excel",
    "application/vnd.ms-powerpoint": "PowerPoint",
    "application/pdf": "PDF",
    "text/plain": "Text",
    "application/vnd.oasis.opendocument.text": "ODT",
    "application/vnd.oasis.opendocument.spreadsheet": "ODS",
}

ROOT = Path(__file__).parent


def label_of(mime: str) -> str:
    return MIME_LABELS.get(mime, mime.rsplit("/", 1)[-1] if "/" in mime else mime or "File")


def get_creds():
    token_path = ROOT / "token.json"
    cred_path = ROOT / "credentials.json"
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            creds = None
        if creds and not set(SCOPES).issubset(set(creds.scopes or [])):
            print("Stored token is missing the new scopes; re-running OAuth flow.")
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            if not cred_path.exists():
                sys.exit(f"Missing {cred_path}. See README.md for OAuth setup.")
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return creds


def get_user_email(creds) -> str:
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return drive.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]


def list_candidate_files(creds, since_iso):
    """Files modified in the window where the user is an owner or writer."""
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    q = f"modifiedTime > '{since_iso}' and trashed=false and 'me' in owners"
    files = []
    page_token = None
    while True:
        resp = drive.files().list(
            q=q,
            fields="nextPageToken, files(id, name, mimeType)",
            pageSize=200,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return [f for f in files if f.get("mimeType") != "application/vnd.google-apps.folder"]


def fetch_activity_for_file(activity, file_id, since_dt):
    """Per-file query, no consolidation. Returns sorted list of edit timestamps (datetimes)."""
    events = []
    page_token = None
    while True:
        body = {
            "itemName": f"items/{file_id}",
            "filter": f'time >= "{since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")}"',
            "consolidationStrategy": {"none": {}},
            "pageSize": 100,
        }
        if page_token:
            body["pageToken"] = page_token
        try:
            resp = activity.activity().query(body=body).execute()
        except Exception as e:
            print(f"    error: {e}")
            return events
        for act in resp.get("activities", []):
            is_me = any(
                ((a.get("user") or {}).get("knownUser") or {}).get("isCurrentUser")
                for a in act.get("actors", [])
            )
            if not is_me:
                continue
            actions = act.get("actions", [])
            if not any(("edit" in (a.get("detail") or {}) or "create" in (a.get("detail") or {})) for a in actions):
                continue
            ts = act.get("timestamp")
            if not ts:
                tr = act.get("timeRange") or {}
                ts = tr.get("endTime") or tr.get("startTime")
            if not ts:
                continue
            events.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return sorted(set(events))


def merge_into_sessions(timestamps, gap_minutes=10, min_duration_minutes=2):
    """Group consecutive timestamps into sessions. Gap > gap_minutes starts a new session."""
    if not timestamps:
        return []
    sessions = []
    start = end = timestamps[0]
    for t in timestamps[1:]:
        if (t - end).total_seconds() / 60 <= gap_minutes:
            end = t
        else:
            sessions.append((start, end))
            start = end = t
    sessions.append((start, end))
    out = []
    for s, e in sessions:
        if (e - s).total_seconds() / 60 < min_duration_minutes:
            e = s + timedelta(minutes=min_duration_minutes)
        out.append({"start": s.isoformat(), "end": e.isoformat()})
    return out


def render_html(payload):
    template = (ROOT / "calendar_template.html").read_text()
    data_json = json.dumps(payload).replace("</", "<\\/")
    (ROOT / "calendar.html").write_text(template.replace("__DATA_PLACEHOLDER__", data_json))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="Look back this many days (default: 30)")
    args = ap.parse_args()

    creds = get_creds()
    user_email = get_user_email(creds)
    since_dt = datetime.now(timezone.utc) - timedelta(days=args.days)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"Signed in as {user_email}")
    print(f"Listing files I've owned/written since {since_iso}...")
    files = list_candidate_files(creds, since_iso)
    print(f"  {len(files)} candidate files. Querying Drive Activity per file...")

    activity = build("driveactivity", "v2", credentials=creds, cache_discovery=False)
    files_out = []
    for i, f in enumerate(files, 1):
        timestamps = fetch_activity_for_file(activity, f["id"], since_dt)
        sessions = merge_into_sessions(timestamps, gap_minutes=10, min_duration_minutes=2)
        print(f"  [{i}/{len(files)}] {f['name'][:55]:55s}  {len(timestamps):4d} edits / {len(sessions):3d} sessions")
        if not sessions:
            continue
        files_out.append({
            "id": f["id"],
            "name": f["name"],
            "type": label_of(f.get("mimeType", "")),
            "mime": f.get("mimeType", ""),
            "link": f"https://drive.google.com/open?id={f['id']}",
            "sessions": sessions,
        })
    files_out.sort(key=lambda f: f["sessions"][-1]["end"], reverse=True)

    payload = {
        "user_email": user_email,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "since": since_dt.isoformat(),
        "days": args.days,
        "source": "drive-activity-v2",
        "files": files_out,
    }
    (ROOT / "activity.json").write_text(json.dumps(payload, indent=2))
    render_html(payload)
    total_sessions = sum(len(f["sessions"]) for f in files_out)
    total_minutes = sum(
        (datetime.fromisoformat(s["end"]) - datetime.fromisoformat(s["start"])).total_seconds() / 60
        for f in files_out for s in f["sessions"]
    )
    print(f"\nWrote activity.json ({len(files_out)} files, {total_sessions} sessions, {total_minutes:.0f} min total)")
    print("Open calendar.html in your browser.")


if __name__ == "__main__":
    main()
