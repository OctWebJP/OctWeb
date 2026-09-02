#!/usr/bin/env node
// Aggregates GitHub Pages traffic (views/clones/referrers/paths) for every
// repo in the org that has Pages enabled, and prints a Markdown report to stdout.
//
// Env:
//   GH_TOKEN  - token with repo scope on all target repos (traffic API requires push)
//   ORG       - org login (default: OctWebJP)

import { Octokit } from "@octokit/rest";

const org = process.env.ORG || "OctWebJP";
const token = process.env.GH_TOKEN;
if (!token) {
  console.error("GH_TOKEN is required");
  process.exit(1);
}

const octokit = new Octokit({ auth: token });

async function getPagesRepos() {
  const repos = await octokit.paginate(octokit.repos.listForOrg, {
    org,
    per_page: 100,
    type: "all",
  });
  return repos.filter((r) => r.has_pages && !r.archived);
}

async function safe(fn, fallback) {
  try {
    return await fn();
  } catch (e) {
    return { error: e.message, ...(fallback || {}) };
  }
}

function fmtTable(headers, rows) {
  if (rows.length === 0) return "_no data_";
  const head = `| ${headers.join(" | ")} |`;
  const sep = `| ${headers.map(() => "---").join(" | ")} |`;
  const body = rows.map((r) => `| ${r.join(" | ")} |`).join("\n");
  return [head, sep, body].join("\n");
}

async function reportForRepo(repo) {
  const params = { owner: org, repo: repo.name };
  const [views, clones, referrers, paths, pages] = await Promise.all([
    safe(() => octokit.repos.getViews({ ...params, per: "day" }).then((r) => r.data), { count: 0, uniques: 0, views: [] }),
    safe(() => octokit.repos.getClones({ ...params, per: "day" }).then((r) => r.data), { count: 0, uniques: 0, clones: [] }),
    safe(() => octokit.repos.getTopReferrers(params).then((r) => r.data), []),
    safe(() => octokit.repos.getTopPaths(params).then((r) => r.data), []),
    safe(() => octokit.repos.getPages(params).then((r) => r.data), null),
  ]);

  const pagesUrl = pages && pages.html_url ? pages.html_url : `https://${org.toLowerCase()}.github.io/${repo.name}/`;

  const viewsRows = (views.views || []).slice(-14).map((v) => [
    v.timestamp.slice(0, 10),
    String(v.count),
    String(v.uniques),
  ]);

  const referrerRows = (Array.isArray(referrers) ? referrers : []).map((r) => [
    r.referrer,
    String(r.count),
    String(r.uniques),
  ]);

  const pathRows = (Array.isArray(paths) ? paths : []).map((p) => [
    `\`${p.path}\``,
    (p.title || "").replace(/\|/g, "\\|"),
    String(p.count),
    String(p.uniques),
  ]);

  return `## [${repo.name}](${pagesUrl})

- 14-day views: **${views.count ?? 0}** (unique: **${views.uniques ?? 0}**)
- 14-day clones: **${clones.count ?? 0}** (unique: **${clones.uniques ?? 0}**)

### Daily views (last 14 days)

${fmtTable(["date", "views", "uniques"], viewsRows)}

### Top referrers

${fmtTable(["referrer", "views", "uniques"], referrerRows)}

### Top paths

${fmtTable(["path", "title", "views", "uniques"], pathRows)}
`;
}

const today = new Date().toISOString().slice(0, 10);
const repos = await getPagesRepos();

let totalViews = 0;
let totalUniques = 0;
const sections = [];
for (const repo of repos) {
  const section = await reportForRepo(repo);
  sections.push(section);
  const match = section.match(/14-day views: \*\*(\d+)\*\* \(unique: \*\*(\d+)\*\*/);
  if (match) {
    totalViews += Number(match[1]);
    totalUniques += Number(match[2]);
  }
}

const header = `# GitHub Pages traffic report — ${today}

Org: **${org}** · Pages sites analyzed: **${repos.length}**

**Org totals (14 days):** ${totalViews} views · ${totalUniques} unique visitors

> Source: GitHub Repository Traffic API (views/clones/referrers/paths). GitHub Pages does not expose raw HTTP access logs; this report reflects the same data shown on each repo's Insights → Traffic page.
`;

console.log([header, ...sections].join("\n"));
