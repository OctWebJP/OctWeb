#!/usr/bin/env python3
"""Generate a daily GitHub Pages traffic report and post it as an issue.

Data source: GitHub Repository Traffic API (views, clones, popular paths,
referrers). This is the closest proxy GitHub exposes for "access logs" on
GitHub Pages-hosted sites. The Pages CDN itself does not expose raw logs.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"


def gh(path: str, token: str) -> dict | list | None:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "octwebjp-pages-traffic-report",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  ! {path} -> HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ! {path} -> {e}", file=sys.stderr)
        return None


def list_pages_repos(org: str, token: str) -> list[dict]:
    repos: list[dict] = []
    page = 1
    while True:
        data = gh(f"/orgs/{org}/repos?per_page=100&page={page}", token) or []
        if not data:
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return [r for r in repos if r.get("has_pages") and not r.get("archived")]


def fmt_repo_section(org: str, repo: str, token: str) -> str:
    views = gh(f"/repos/{org}/{repo}/traffic/views", token) or {}
    clones = gh(f"/repos/{org}/{repo}/traffic/clones", token) or {}
    paths = gh(f"/repos/{org}/{repo}/traffic/popular/paths", token) or []
    refs = gh(f"/repos/{org}/{repo}/traffic/popular/referrers", token) or []

    pages_info = gh(f"/repos/{org}/{repo}/pages", token) or {}
    site_url = pages_info.get("html_url", f"https://{org.lower()}.github.io/{repo}/")

    out = [f"### 📄 [{org}/{repo}]({site_url})", ""]
    out.append(
        f"- **Views (14d):** {views.get('count', 0)} total · "
        f"{views.get('uniques', 0)} unique"
    )
    out.append(
        f"- **Clones (14d):** {clones.get('count', 0)} total · "
        f"{clones.get('uniques', 0)} unique"
    )

    # Yesterday's slice
    daily = views.get("views", [])
    if daily:
        last = daily[-1]
        out.append(
            f"- **Latest day ({last['timestamp'][:10]}):** "
            f"{last['count']} views · {last['uniques']} unique"
        )

    if paths:
        out.append("")
        out.append("**Top paths (14d):**")
        out.append("")
        out.append("| Path | Views | Unique |")
        out.append("|------|------:|------:|")
        for p in paths[:10]:
            path = p["path"].replace("|", "\\|")
            out.append(f"| `{path}` | {p['count']} | {p['uniques']} |")

    if refs:
        out.append("")
        out.append("**Top referrers (14d):**")
        out.append("")
        out.append("| Referrer | Views | Unique |")
        out.append("|----------|------:|------:|")
        for r in refs[:10]:
            out.append(f"| {r['referrer']} | {r['count']} | {r['uniques']} |")

    if not paths and not refs and not views.get("count"):
        out.append("")
        out.append("_No traffic recorded in the last 14 days._")

    out.append("")
    return "\n".join(out)


def main() -> int:
    org = os.environ["ORG"]
    traffic_token = os.environ["GH_TRAFFIC_TOKEN"]
    issue_token = os.environ["GH_ISSUE_TOKEN"]
    issue_repo = os.environ["ISSUE_REPO"]  # owner/repo

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Listing Pages-enabled repos in {org}...")
    repos = list_pages_repos(org, traffic_token)
    print(f"Found {len(repos)} Pages-enabled repos: {[r['name'] for r in repos]}")

    sections: list[str] = []
    totals_views = totals_unique = 0
    for r in repos:
        print(f"Fetching traffic for {r['name']}...")
        sections.append(fmt_repo_section(org, r["name"], traffic_token))
        v = gh(f"/repos/{org}/{r['name']}/traffic/views", traffic_token) or {}
        totals_views += v.get("count", 0)
        totals_unique += v.get("uniques", 0)

    title = f"📊 GitHub Pages traffic report — {today}"
    body_parts = [
        f"_Daily traffic snapshot for **{org}** GitHub Pages sites. "
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._",
        "",
        "## Summary (last 14 days, all Pages repos)",
        f"- **Total views:** {totals_views}",
        f"- **Total unique visitors:** {totals_unique}",
        f"- **Pages-enabled repos analyzed:** {len(repos)}",
        "",
        "## Per-repo breakdown",
        "",
        *sections,
        "---",
        "Source: GitHub Repository Traffic API (`/repos/:owner/:repo/traffic/*`). "
        "GitHub Pages does not expose raw web-server access logs; this report uses "
        "GitHub's built-in 14-day traffic insights as the closest available proxy. "
        "For richer analytics add a tracker (Plausible, GoatCounter, GA) to each site.",
    ]
    body = "\n".join(body_parts)

    owner, repo = issue_repo.split("/", 1)
    payload = json.dumps(
        {"title": title, "body": body, "labels": ["traffic-report", "automated"]}
    ).encode()
    req = urllib.request.Request(
        f"{API}/repos/{owner}/{repo}/issues",
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {issue_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "octwebjp-pages-traffic-report",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        created = json.loads(r.read().decode())
    print(f"Created issue #{created['number']}: {created['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
