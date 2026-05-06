"""Shared utilities for activity sources."""
from datetime import datetime, timedelta


def merge_into_sessions(timestamps, gap_minutes=10, min_duration_minutes=2):
    """Group consecutive (sorted) datetime objects into sessions.

    A new session starts when the gap from the previous timestamp exceeds
    `gap_minutes`. Sessions shorter than `min_duration_minutes` are padded.
    Returns list of {"start": iso, "end": iso} dicts.
    """
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


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))
