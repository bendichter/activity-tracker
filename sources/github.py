"""GitHub activity source: commits + authored PRs/issues + reviews + comments.

Uses a Personal Access Token from .env (GITHUB_PAT). Aggregates events per
repo and merges them into work sessions.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from .common import merge_into_sessions, parse_iso

API = "https://api.github.com"


def _headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(url, token, params=None):
    for attempt in range(3):
        r = requests.get(url, headers=_headers(token), params=params, timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("X-RateLimit-Reset", "0"))
            wait = max(reset - int(time.time()), 1) + 1
            print(f"  rate-limited; sleeping {wait}s")
            time.sleep(min(wait, 60))
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        if not r.ok:
            raise requests.HTTPError(
                f"{r.status_code} {r.reason} for {r.url}\n  body: {r.text[:500]}",
                response=r,
            )
        return r.json()
    r.raise_for_status()


def _search_paginated(endpoint, query, token, max_pages=10, sort=None):
    items = []
    for page in range(1, max_pages + 1):
        params = {"q": query, "per_page": 100, "page": page}
        if sort:
            params["sort"] = sort
            params["order"] = "desc"
        data = _get(f"{API}/search/{endpoint}", token, params)
        page_items = data.get("items", [])
        items.extend(page_items)
        if len(page_items) < 100:
            break
    return items


def _repo_from_url(repo_url):
    return repo_url.split("/repos/", 1)[-1] if "/repos/" in repo_url else repo_url


def fetch(root: Path, since_dt: datetime):
    """Returns list of items, one per repo. Each item: {kind:'github', id, name, type, link, sessions}."""
    token = os.environ.get("GITHUB_PAT")
    if not token:
        print("[github] GITHUB_PAT not set in environment; skipping.")
        return []

    user = _get(f"{API}/user", token)["login"]
    print(f"[github] signed in as {user}")

    since_str = since_dt.strftime("%Y-%m-%d")
    # Activity per repo: list of (datetime, kind, summary, link)
    by_repo = defaultdict(list)

    # 1. Commits authored
    print(f"[github] fetching commits since {since_str}...")
    commits = _search_paginated("commits", f"author:{user} committer-date:>={since_str}", token, max_pages=10)
    for c in commits:
        ts = c["commit"]["committer"]["date"]
        dt = parse_iso(ts)
        if dt < since_dt:
            continue
        repo = c["repository"]["full_name"]
        by_repo[repo].append((dt, "commit", c["commit"]["message"].split("\n", 1)[0], c["html_url"]))
    print(f"  {len(commits)} commits across {len({c['repository']['full_name'] for c in commits})} repos")

    # 2. Issues + PRs authored — created_at gives accurate timestamp
    print("[github] fetching issues/PRs authored...")
    authored = (
        _search_paginated("issues", f"is:issue author:{user} created:>={since_str}", token, max_pages=10)
        + _search_paginated("issues", f"is:pull-request author:{user} created:>={since_str}", token, max_pages=10)
    )
    for it in authored:
        dt = parse_iso(it["created_at"])
        if dt < since_dt:
            continue
        repo = _repo_from_url(it["repository_url"])
        kind = "pr-open" if it.get("pull_request") else "issue-open"
        by_repo[repo].append((dt, kind, f"#{it['number']}: {it['title']}", it["html_url"]))
    print(f"  {len(authored)} authored items")

    # 3. Issue / PR comments (need accurate timestamps via per-item secondary fetch)
    print("[github] fetching commented threads...")
    commented = (
        _search_paginated("issues", f"is:issue commenter:{user} updated:>={since_str}", token, max_pages=10)
        + _search_paginated("issues", f"is:pull-request commenter:{user} updated:>={since_str}", token, max_pages=10)
    )
    print(f"  {len(commented)} threads with my comments; fetching comment timestamps...")
    for j, it in enumerate(commented, 1):
        repo = _repo_from_url(it["repository_url"])
        number = it["number"]
        try:
            comments = _get(f"{API}/repos/{repo}/issues/{number}/comments", token, {"per_page": 100})
        except Exception as e:
            print(f"    skip {repo}#{number}: {e}")
            continue
        for c in comments:
            if (c.get("user") or {}).get("login") != user:
                continue
            dt = parse_iso(c["created_at"])
            if dt < since_dt:
                continue
            by_repo[repo].append((dt, "comment", f"comment on #{number}: {it['title']}", c["html_url"]))

    # 4. PR reviews (also need accurate timestamps)
    print("[github] fetching PR reviews...")
    reviewed = _search_paginated("issues", f"is:pull-request reviewed-by:{user} updated:>={since_str}", token, max_pages=10)
    print(f"  {len(reviewed)} PRs reviewed; fetching review timestamps...")
    for j, it in enumerate(reviewed, 1):
        repo = _repo_from_url(it["repository_url"])
        number = it["number"]
        try:
            reviews = _get(f"{API}/repos/{repo}/pulls/{number}/reviews", token, {"per_page": 100})
        except Exception as e:
            print(f"    skip {repo}#{number}: {e}")
            continue
        for rv in reviews:
            if (rv.get("user") or {}).get("login") != user:
                continue
            ts = rv.get("submitted_at")
            if not ts:
                continue
            dt = parse_iso(ts)
            if dt < since_dt:
                continue
            by_repo[repo].append((dt, "review", f"review on #{number}: {it['title']}", rv.get("html_url", it["html_url"])))

    # Aggregate to items
    items = []
    for repo, events in by_repo.items():
        events.sort(key=lambda x: x[0])
        timestamps = [e[0] for e in events]
        sessions = merge_into_sessions(timestamps)
        if not sessions:
            continue
        # Annotate sessions with the events that fall inside
        for s in sessions:
            s_start = parse_iso(s["start"])
            s_end = parse_iso(s["end"])
            inside = [e for e in events if s_start <= e[0] <= s_end]
            s["events"] = [{"kind": k, "summary": summ, "link": link, "ts": dt.isoformat()} for dt, k, summ, link in inside]
        items.append({
            "kind": "github",
            "id": repo,
            "name": repo,
            "type": "GitHub",
            "link": f"https://github.com/{repo}",
            "sessions": sessions,
        })
    items.sort(key=lambda x: x["sessions"][-1]["end"], reverse=True)
    print(f"[github] {len(items)} repos with activity; "
          f"{sum(len(i['sessions']) for i in items)} total sessions")
    return items
