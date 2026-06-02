#!/usr/bin/env python3
"""Generate a daily traffic report for every GitHub Pages site in the org.

GitHub Pages does not expose raw HTTP access logs. This script uses the
closest GitHub-native proxy: the repository Traffic API
(views / clones / popular paths / popular referrers, last 14 days).

Env:
  GH_TOKEN  - PAT with `repo` scope (or fine-grained: Administration: read
              on the target repos, plus Issues: write on the issue repo).
              Required for traffic endpoints, which need push access.
  ORG       - org login (default: OctWebJP)
  ISSUE_REPO- repo (within ORG) where the issue is created (default: OctWeb)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ORG = os.environ.get("ORG", "OctWebJP")
ISSUE_REPO = os.environ.get("ISSUE_REPO", "OctWeb")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    sys.exit("GH_TOKEN (or GITHUB_TOKEN) env var is required")

API = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "octwebjp-pages-traffic-report",
}


def gh(path: str):
    req = urllib.request.Request(f"{API}{path}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


def list_pages_repos() -> list[dict]:
    out, page = [], 1
    while True:
        batch = gh(f"/orgs/{ORG}/repos?per_page=100&page={page}")
        if isinstance(batch, dict) and batch.get("_error"):
            sys.exit(f"Failed to list repos: {batch['_error']}")
        if not batch:
            break
        out.extend(r for r in batch if r.get("has_pages"))
        if len(batch) < 100:
            break
        page += 1
    return out


def pages_url(repo: dict) -> str:
    info = gh(f"/repos/{ORG}/{repo['name']}/pages")
    if isinstance(info, dict) and not info.get("_error"):
        return info.get("html_url") or ""
    return ""


def fmt_daily(series: list[dict], key: str) -> str:
    if not series:
        return "_no data_"
    lines = ["| Date | Count | Uniques |", "| --- | ---:| ---:|"]
    for d in series:
        date = d["timestamp"][:10]
        lines.append(f"| {date} | {d['count']} | {d['uniques']} |")
    return "\n".join(lines)


def fmt_paths(items: list[dict]) -> str:
    if not items:
        return "_no data_"
    lines = ["| Path | Title | Views | Uniques |", "| --- | --- | ---:| ---:|"]
    for it in items:
        lines.append(
            f"| `{it['path']}` | {it.get('title','')} | {it['count']} | {it['uniques']} |"
        )
    return "\n".join(lines)


def fmt_refs(items: list[dict]) -> str:
    if not items:
        return "_no data_"
    lines = ["| Referrer | Views | Uniques |", "| --- | ---:| ---:|"]
    for it in items:
        lines.append(f"| {it['referrer']} | {it['count']} | {it['uniques']} |")
    return "\n".join(lines)


def build_report() -> tuple[str, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    repos = list_pages_repos()
    parts = [
        f"# GitHub Pages Traffic Report — {today} (UTC)",
        "",
        f"Organization: **{ORG}** · Pages-enabled repos: **{len(repos)}**",
        "",
        "> ⚠️ GitHub Pages does not expose raw HTTP access logs. "
        "This report uses the repository Traffic API "
        "(rolling 14-day window of views, clones, popular paths, and referrers) "
        "as the closest available proxy.",
        "",
    ]

    summary = [
        "## Summary (last 14 days)",
        "| Repo | Pages URL | Views | Unique Visitors | Clones | Unique Cloners |",
        "| --- | --- | ---:| ---:| ---:| ---:|",
    ]
    details = []

    for repo in repos:
        name = repo["name"]
        full = f"{ORG}/{name}"
        url = pages_url(repo)
        v = gh(f"/repos/{full}/traffic/views")
        c = gh(f"/repos/{full}/traffic/clones")
        p = gh(f"/repos/{full}/traffic/popular/paths")
        r = gh(f"/repos/{full}/traffic/popular/referrers")

        vt = v.get("count", 0) if isinstance(v, dict) and "_error" not in v else 0
        vu = v.get("uniques", 0) if isinstance(v, dict) and "_error" not in v else 0
        ct = c.get("count", 0) if isinstance(c, dict) and "_error" not in c else 0
        cu = c.get("uniques", 0) if isinstance(c, dict) and "_error" not in c else 0

        note = ""
        if isinstance(v, dict) and v.get("_error"):
            note = f" ⚠️ traffic unavailable: `{v['_error'][:80]}`"

        summary.append(
            f"| [{name}](https://github.com/{full}) | "
            f"{(f'[{url}]({url})' if url else '_n/a_')} | "
            f"{vt} | {vu} | {ct} | {cu} |{note}"
        )

        details.extend([
            f"## {name}",
            f"- Repo: https://github.com/{full}",
            f"- Pages URL: {url or '_unknown_'}",
            "",
            "### Daily views",
            fmt_daily(v.get("views", []) if isinstance(v, dict) else [], "views"),
            "",
            "### Daily clones",
            fmt_daily(c.get("clones", []) if isinstance(c, dict) else [], "clones"),
            "",
            "### Popular paths (14d)",
            fmt_paths(p if isinstance(p, list) else []),
            "",
            "### Top referrers (14d)",
            fmt_refs(r if isinstance(r, list) else []),
            "",
        ])

    body = "\n".join(parts + summary + [""] + details)
    title = f"Pages Traffic Report — {today}"
    return title, body


def ensure_label():
    data = json.dumps({
        "name": "pages-traffic",
        "color": "0e8a16",
        "description": "Daily GitHub Pages traffic reports",
    }).encode()
    req = urllib.request.Request(
        f"{API}/repos/{ORG}/{ISSUE_REPO}/labels",
        data=data, headers=HEADERS, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        if e.code != 422:  # already exists
            print(f"warn: label create: {e.code}", file=sys.stderr)


def create_issue(title: str, body: str) -> str:
    ensure_label()
    data = json.dumps({"title": title, "body": body, "labels": ["pages-traffic"]}).encode()
    req = urllib.request.Request(
        f"{API}/repos/{ORG}/{ISSUE_REPO}/issues",
        data=data, headers=HEADERS, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["html_url"]


def main():
    title, body = build_report()
    if os.environ.get("DRY_RUN"):
        print(title); print(); print(body); return
    print(create_issue(title, body))


if __name__ == "__main__":
    main()
