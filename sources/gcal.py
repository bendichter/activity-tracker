"""Google Calendar source: events from all selected (visible) calendars.

Excludes all-day events and events the user declined. Each event becomes a
session within a per-calendar item; the event's summary is carried on the
session for the calendar UI to display.
"""
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from .common import parse_iso


def _list_visible_calendars(cal):
    cals = []
    page_token = None
    while True:
        resp = cal.calendarList().list(pageToken=page_token, maxResults=250).execute()
        cals.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    out = []
    for c in cals:
        if c.get("hidden"):
            continue
        if c.get("selected") is False:
            continue
        out.append(c)
    return out


def _list_events(cal, calendar_id, time_min, time_max):
    events = []
    page_token = None
    while True:
        resp = cal.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            showDeleted=False,
            orderBy="startTime",
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def _self_attendee(event):
    for a in event.get("attendees", []) or []:
        if a.get("self"):
            return a
    return None


def _user_involved(event):
    """True if the current user is the organizer/creator OR a non-declined attendee.
    Events on subscribed colleague calendars that the user isn't invited to are
    filtered out. Events with hidden summaries (private events on shared calendars)
    naturally fall in this bucket.
    """
    if (event.get("organizer") or {}).get("self"):
        return True
    if (event.get("creator") or {}).get("self"):
        return True
    a = _self_attendee(event)
    if a and a.get("responseStatus") != "declined":
        return True
    return False


def fetch(creds, since_dt: datetime):
    cal = build("calendar", "v3", credentials=creds, cache_discovery=False)
    calendars = _list_visible_calendars(cal)
    print(f"[gcal] {len(calendars)} visible calendars")

    until_dt = datetime.now(timezone.utc) + timedelta(days=1)
    time_min = since_dt.isoformat().replace("+00:00", "Z")
    time_max = until_dt.isoformat().replace("+00:00", "Z")

    items = []
    total_events = 0
    seen_uids = set()  # dedupe events that appear on multiple calendars
    for c in calendars:
        cal_id = c["id"]
        cal_name = c.get("summaryOverride") or c.get("summary") or cal_id
        cal_color = c.get("backgroundColor") or "#4285f4"
        events = _list_events(cal, cal_id, time_min, time_max)
        sessions = []
        skipped_uninvolved = 0
        for e in events:
            start = e.get("start") or {}
            end = e.get("end") or {}
            if "dateTime" not in start:
                continue
            if e.get("status") == "cancelled":
                continue
            if not _user_involved(e):
                skipped_uninvolved += 1
                continue
            uid = e.get("iCalUID") or e.get("id")
            dedupe_key = (uid, start["dateTime"])
            if uid and dedupe_key in seen_uids:
                continue
            seen_uids.add(dedupe_key)
            sessions.append({
                "start": start["dateTime"],
                "end": end.get("dateTime") or start["dateTime"],
                "title": e.get("summary") or "(no title)",
                "events": [{
                    "kind": "event",
                    "summary": e.get("summary") or "(no title)",
                    "link": e.get("htmlLink", ""),
                    "ts": start["dateTime"],
                }],
            })
        if skipped_uninvolved:
            print(f"  {cal_name[:40]:40s}  ({skipped_uninvolved} events skipped — not invited)")
        if not sessions:
            continue
        sessions.sort(key=lambda s: s["start"])
        total_events += len(sessions)
        items.append({
            "kind": "event",
            "id": f"cal:{cal_id}",
            "name": cal_name,
            "type": "Calendar",
            "color": cal_color,
            "link": f"https://calendar.google.com/calendar/u/0/r?cid={cal_id}",
            "sessions": sessions,
        })
        print(f"  {cal_name[:40]:40s}  {len(sessions):4d} events kept")
    print(f"[gcal] {total_events} events across {len(items)} calendars")
    return items
