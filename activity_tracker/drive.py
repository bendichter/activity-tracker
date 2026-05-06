"""Google Drive activity source: per-file edit events from Drive Activity API."""
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build

from .common import merge_into_sessions, parse_iso

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


def label_of(mime: str) -> str:
    return MIME_LABELS.get(mime, mime.rsplit("/", 1)[-1] if "/" in mime else mime or "File")


def get_user_email(creds) -> str:
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return drive.about().get(fields="user(emailAddress)").execute()["user"]["emailAddress"]


def list_owned_files(creds, since_iso: str, until_iso: str):
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    q = (
        f"modifiedTime > '{since_iso}' and modifiedTime < '{until_iso}' "
        "and trashed=false and 'me' in owners"
    )
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


def fetch_activity_for_file(activity, file_id: str, since_dt: datetime, until_dt: datetime):
    events = []
    page_token = None
    since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    until_str = until_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    while True:
        body = {
            "itemName": f"items/{file_id}",
            "filter": f'time >= "{since_str}" AND time < "{until_str}"',
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
            events.append(parse_iso(ts))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return sorted(set(events))


def fetch(creds, since_dt: datetime, until_dt: datetime):
    """Returns (user_email, items[]). Each item: {kind, id, name, type, link, sessions}."""
    user_email = get_user_email(creds)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    until_iso = until_dt.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[drive] signed in as {user_email}")
    print(f"[drive] listing owned files modified between {since_iso} and {until_iso}...")
    files = list_owned_files(creds, since_iso, until_iso)
    print(f"[drive] {len(files)} candidates; querying activity per file...")

    activity = build("driveactivity", "v2", credentials=creds, cache_discovery=False)
    items = []
    for i, f in enumerate(files, 1):
        timestamps = fetch_activity_for_file(activity, f["id"], since_dt, until_dt)
        sessions = merge_into_sessions(timestamps)
        if not sessions:
            continue
        items.append({
            "kind": "doc",
            "id": f["id"],
            "name": f["name"],
            "type": label_of(f.get("mimeType", "")),
            "mime": f.get("mimeType", ""),
            "link": f"https://drive.google.com/open?id={f['id']}",
            "sessions": sessions,
        })
        print(f"  [{i}/{len(files)}] {f['name'][:55]:55s}  {len(timestamps):4d} edits / {len(sessions):3d} sessions")
    items.sort(key=lambda x: x["sessions"][-1]["end"], reverse=True)
    return user_email, items
