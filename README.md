# Activity Tracker

Visualize your real workday as a week calendar. Pulls activity from Google Drive (Docs / Sheets / Slides), Google Calendar, and GitHub, merges events into work sessions, and renders a browsable HTML view — think Google Calendar, but every block is "you edited X from 2:14 to 3:08."

Useful for reconstructing where your time actually went, writing reports, or backfilling a time-tracking tool.

## Sources

- **Google Drive** — Docs, Sheets, Slides, Word, Excel, PDF, etc. that you edited, via the Drive Activity API. Includes files you own *and* files shared with you that you have write access to (e.g., colleagues' docs you collaborate on).
- **Google Calendar** — events on your visible calendars where you're the organizer or a non-declined attendee.
- **GitHub** — commits authored, issues / PRs opened, comments posted, PR reviews submitted.

Each source can be skipped independently with `--skip-drive`, `--skip-gcal`, `--skip-github`.

## Setup

### 1. Google OAuth (Drive + Calendar)

The Drive API treats your revision history as private user data, so a plain API key won't work — you need OAuth. One-time setup:

1. Go to https://console.cloud.google.com/ and create (or pick) a project.
2. **APIs & Services → Library** → enable **Google Drive API** and **Google Calendar API**.
3. **APIs & Services → OAuth consent screen** → External → fill required fields → add your own email under "Test users".
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** → Application type **Desktop app**.
5. Download the JSON and save it as `credentials.json` in the directory you'll run the tool from.

Required scopes (requested automatically on first run):
- `drive.activity.readonly`, `drive.metadata.readonly`
- `calendar.readonly`

### 2. GitHub PAT (optional, for the GitHub source)

Create a fine-grained personal access token at https://github.com/settings/tokens with read access to the repos you care about. Put it in a `.env` file in your working directory:

```
GITHUB_PAT=ghp_...
```

If `GITHUB_PAT` is unset, the GitHub source is silently skipped.

### 3. Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install .                # or: pip install -e . for development
```

## Usage

Run from a directory containing your `credentials.json` (and optionally `.env`). Outputs (`activity.json`, `calendar.html`, `token.json`) are written to the current directory.

```bash
activity-tracker                                       # last 30 days, ending now
activity-tracker --start 2026-05-01                    # from May 1 to now
activity-tracker --start 2026-05-01 --end 2026-05-05   # explicit window
activity-tracker --skip-github                         # only Drive + Calendar
```

Bounds accept `YYYY-MM-DD` (date-only) or full ISO datetimes. `--end` defaults to now; `--start` defaults to 30 days before `--end`. Date-only `--start` is interpreted as 00:00 UTC and date-only `--end` as 23:59:59 UTC.

First run opens a browser for OAuth consent and writes `token.json` for future runs.

```bash
open calendar.html
```

## Calendar UI

- Week view, 7 columns × 24 hours.
- Each block = one work session on one file / repo / event. Color is stable per item.
- Hover for full title + duration. Click to open the source in its native app (Google Drive, GitHub, Google Calendar).
- **Drive / GitHub / Calendar** checkboxes hide / show entire sources.
- **Merge gap** (top bar): timestamps closer than this collapse into one session. Default 10 min.
- **Min session**: pads short sessions to this length so they're visible. Default 2 min.
- `←` / `→` / `T` for prev week / next week / today.

## Notes & caveats

- Drive: candidate files are those you have write access to and were modified in your window. Per-file, only activity events where *you* are the actor count toward sessions — so a colleague's edits on a shared doc don't show up in your calendar.
- Drive only stores the revision history Google decides to keep; short edit bursts can be coalesced server-side. Sessions are an approximation, not a keystroke log.
- GitHub comment / review searches use `updated:>=since` to find threads, then filter the actual comment / review timestamps in-range — so a thread you commented on in your window will be picked up even if it was last updated outside it.
- `token.json`, `credentials.json`, and `.env` are secrets. The included `.gitignore` excludes them.

## License

MIT
