# Google Workspace Activity Tracker

A small tool to backfill Toggl from your actual Google Docs / Sheets / Slides activity. Pulls revision history from the Google Drive API, merges revisions into work sessions, and renders a week calendar (think Google Calendar, but every event is "you edited X from 2:14 to 3:08").

## Setup

### 1. Create OAuth credentials

The Drive API treats your revision history as private user data, so a plain API key won't work — you need OAuth. One-time setup:

1. Go to https://console.cloud.google.com/ and create (or pick) a project.
2. **APIs & Services → Library** → enable **Google Drive API**.
3. **APIs & Services → OAuth consent screen** → External → fill required fields → add your own email under "Test users".
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type **Desktop app**.
5. Download the JSON. Save it as `credentials.json` in this directory.

### 2. Install dependencies

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run

```bash
python fetch.py            # last 30 days
python fetch.py --days 60  # custom window
```

First run opens a browser for OAuth consent and saves `token.json` for future runs. When done it writes `activity.json` and `calendar.html`.

```bash
open calendar.html
```

## Calendar UI

- Week view, 7 columns × 24 hours.
- Each block = one work session on one file. Color is per-file (stable hash of file ID).
- Hover for full file name + duration. Click to open the doc in Google.
- **Merge gap** (top bar): revisions closer than this gap collapse into one session. Default 10 min.
- **Min session**: pads very short sessions to this length so they're visible / useful for time tracking. Default 2 min.
- Arrow keys / `T` for prev / next / today.
- **Export Toggl CSV** dumps the visible week.

## Toggl import

Toggl Track → **Profile → Data import → Import from CSV**. The exported file uses these columns:

`Email, Project, Description, Start date, Start time, End date, End time, Duration`

Toggl will create projects on the fly (`Doc`, `Sheet`, `Slides`, etc.). Adjust before importing if you'd rather map all to one project.

## Notes

- Only files where you are the owner and you are the last modifier of the revision are included.
- Drive only stores the revision history Google decides to keep — short edit bursts can be coalesced server-side. Sessions are an approximation, not a keystroke log.
- `token.json` and `credentials.json` are secrets. Don't commit them.
