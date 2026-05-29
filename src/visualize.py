"""
Generate a self-contained HTML report with Chart.js bar graphs.

Charts produced:
  1. Overall software distribution (horizontal bar)
  2. Software by province (stacked bar)
  3. Top software per province (grouped bar, top-10 clubs shown)
  4. Software by club-size bucket (if member data available)
  5. Category breakdown (swim-specific vs generic CMS etc.)
  6. Full data table with search / sort
"""

import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

# Colour palette (20 distinct colours)
COLOURS = [
    "#2563EB", "#DC2626", "#16A34A", "#CA8A04", "#9333EA",
    "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#6366F1",
    "#0D9488", "#B45309", "#7C3AED", "#059669", "#D97706",
    "#2DD4BF", "#F472B6", "#A3E635", "#FB923C", "#818CF8",
]

# Homepage URLs for each known platform (used to make bar labels clickable)
PLATFORM_URLS = {
    "Commit":                   "https://www.commitswimming.com",
    "GoMotion":                 "https://www.gomotionapp.com",
    "PoolQ":                    "https://poolq.net",
    "Amilia":                   "https://www.amilia.com",
    "Uplifter":                 "https://www.uplifter.ca",
    "TeamUnify":                "https://www.teamunify.com",
    "Club Assistant":           "https://www.clubassistant.com",
    "SwimTopia":                "https://www.swimtopia.com",
    "Swimmingly":               "https://goswimmingly.com",
    "Webpoint":                 "https://www.webpoint.us",
    "JerseyWatch":              "https://www.jerseywatch.com",
    "TeamLinkt":                "https://www.teamlinkt.com",
    "Sidearm Sports":           "https://sidearmsports.com",
    "Presto Sports":            "https://www.prestosports.com",
    "GoalLine (Stack Sports)":  "https://www.goalline.ca",
    "Jonas Club Software":      "https://www.jonasclub.com",
    "SportsEngine":             "https://www.sportsengine.com",
    "TeamSnap":                 "https://www.teamsnap.com",
    "Jackrabbit":               "https://www.jackrabbittech.com",
    "iClass Pro":               "https://www.iclasspro.com",
    "Sporty HQ":                "https://sportyhq.com",
    "Active Network":           "https://www.activenetwork.com",
    "Regatta Network":          "https://www.regattanetwork.com",
    "rTeam":                    "https://rteam.com",
    "FinalForms":               "https://www.finalforms.com",
    "WordPress":                "https://wordpress.org",
    "Wix":                      "https://www.wix.com",
    "Squarespace":              "https://www.squarespace.com",
    "Weebly":                   "https://www.weebly.com",
    "Google Sites":             "https://sites.google.com",
    "Jimdo":                    "https://www.jimdo.com",
    "Webflow":                  "https://webflow.com",
    "GoDaddy Website Builder":  "https://www.godaddy.com/websites/website-builder",
    "WebSelf":                  "https://www.webself.net",
    "Duda":                     "https://www.duda.co",
    "Drupal":                   "https://www.drupal.org",
    "Joomla":                   "https://www.joomla.org",
}

# Values that should never appear in the software distribution chart
_EXCLUDE_FROM_DISTRIBUTION = {"Error", "No Website"}


def _colour(i):
    return COLOURS[i % len(COLOURS)]


def _platform_colours(platforms):
    return {p: _colour(i) for i, p in enumerate(sorted(platforms))}


# -------------------------------------------------------------------
# Chart data builders
# -------------------------------------------------------------------

def _overall_chart_html(df):
    """
    Returns a self-contained HTML horizontal bar chart where each platform
    name is a real <a> link to its homepage.  Uses CSS flexbox — no canvas.
    Error and No Website rows are excluded.
    """
    counts = (
        df[~df["software"].isin(_EXCLUDE_FROM_DISTRIBUTION)]["software"]
        .value_counts()
    )
    if counts.empty:
        return "<p>No data.</p>"

    max_count = int(counts.iloc[0])
    rows_html = []
    for i, (name, count) in enumerate(counts.items()):
        colour = _colour(i)
        url = PLATFORM_URLS.get(name)
        if url:
            label = (
                f'<a href="{url}" target="_blank" rel="noreferrer" '
                f'class="sw-link">{name}</a>'
            )
        else:
            label = f'<span class="sw-nolink">{name}</span>'
        pct = count / max_count * 100
        rows_html.append(f"""
      <div class="hbar-row">
        <div class="hbar-label">{label}</div>
        <div class="hbar-track">
          <div class="hbar-fill" style="width:{pct:.1f}%;background:{colour}">
            <span class="hbar-count">{count}</span>
          </div>
        </div>
      </div>""")

    return f"""
<div class="chart-card hbar-card">
  <div class="hbar-title">Team management software — Canadian swim clubs</div>
  <div class="hbar-subtitle">(Error and No Website excluded)</div>
  <div class="hbar-chart">{''.join(rows_html)}
  </div>
</div>"""


def _province_stacked_chart(df, pal):
    provinces = sorted(df["province"].dropna().unique())
    softwares = sorted(df["software"].dropna().unique())

    datasets = []
    for sw in softwares:
        sub = df[df["software"] == sw]
        row = sub.groupby("province").size()
        datasets.append({
            "label": sw,
            "data": [int(row.get(p, 0)) for p in provinces],
            "backgroundColor": pal[sw],
        })

    return {
        "type": "bar",
        "data": {"labels": provinces, "datasets": datasets},
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": "Software distribution by province"},
                "legend": {"position": "right"},
            },
            "scales": {
                "x": {"stacked": True},
                "y": {"stacked": True, "beginAtZero": True},
            },
        },
    }


def _category_chart(df):
    counts = df["category"].value_counts()
    labels = counts.index.tolist()
    data = counts.values.tolist()
    colours = [_colour(i) for i in range(len(labels))]
    return {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [{
                "data": data,
                "backgroundColor": colours,
            }],
        },
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": "Broad category breakdown"},
                "legend": {"position": "right"},
            },
        },
    }


def _size_chart(df):
    """Bar chart of software by member-count bucket (only if data available)."""
    if "members" not in df.columns:
        return None
    has_members = df["members"].notna().sum()
    if has_members < 5:
        return None

    bins = [0, 50, 150, 300, 600, math.inf]
    labels_b = ["<50", "50–150", "150–300", "300–600", "600+"]
    df = df.copy()
    df["size_bucket"] = pd.cut(
        df["members"].fillna(-1).astype(float),
        bins=[-1] + bins[1:],
        labels=["Unknown"] + labels_b,
        right=False,
    )
    top_sw = df["software"].value_counts().head(8).index.tolist()
    sub = df[df["software"].isin(top_sw) & (df["size_bucket"] != "Unknown")]
    pivot = sub.groupby(["size_bucket", "software"]).size().unstack(fill_value=0)

    datasets = []
    for i, sw in enumerate(top_sw):
        if sw in pivot.columns:
            datasets.append({
                "label": sw,
                "data": [int(pivot.at[b, sw]) if b in pivot.index else 0 for b in labels_b],
                "backgroundColor": _colour(i),
            })

    return {
        "type": "bar",
        "data": {"labels": labels_b, "datasets": datasets},
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": "Software by club size (registered swimmers)"},
                "legend": {"position": "right"},
            },
            "scales": {
                "x": {"stacked": True},
                "y": {"stacked": True, "beginAtZero": True},
            },
        },
    }


def _top_per_province_chart(df, pal):
    """Grouped bar – for each province, show its top-3 platforms."""
    provinces = sorted(df["province"].dropna().unique())
    top_sw = df["software"].value_counts().head(10).index.tolist()
    sub = df[df["software"].isin(top_sw)]

    datasets = []
    for sw in top_sw:
        row = sub[sub["software"] == sw].groupby("province").size()
        datasets.append({
            "label": sw,
            "data": [int(row.get(p, 0)) for p in provinces],
            "backgroundColor": pal[sw],
        })

    return {
        "type": "bar",
        "data": {"labels": provinces, "datasets": datasets},
        "options": {
            "responsive": True,
            "plugins": {
                "title": {"display": True, "text": "Top 10 platforms by province (grouped)"},
                "legend": {"position": "right"},
            },
            "scales": {"x": {"beginAtZero": True}, "y": {"beginAtZero": True}},
        },
    }


# -------------------------------------------------------------------
# HTML assembly
# -------------------------------------------------------------------

_CHART_TEMPLATE = """
<div class="chart-card">
  <canvas id="{cid}"></canvas>
</div>
<script>
new Chart(document.getElementById('{cid}'), {cfg});
</script>
"""


# Maps URL domain patterns to short source labels shown in the HTML table.
_SOURCE_LABELS = [
    (re.compile(r"swimontario\.com",   re.I), "Swim ON"),
    (re.compile(r"swimbc\.ca",         re.I), "Swim BC"),
    (re.compile(r"swimalberta\.ca",    re.I), "Swim AB"),
    (re.compile(r"swimmanitoba\.mb\.ca", re.I), "Swim MB"),
    (re.compile(r"swimmingnl\.ca",     re.I), "Swim NL"),
    (re.compile(r"swimming\.ca|findaclub\.swimming\.ca", re.I), "Swimming CA"),
]


def _source_cell(url):
    """Return a <td> for the source_url column: a short linked label."""
    url = str(url) if pd.notna(url) else ""
    if not url:
        return "<td></td>"
    label = url  # fallback: show raw URL
    for pattern, name in _SOURCE_LABELS:
        if pattern.search(url):
            label = name
            break
    return f'<td><a href="{url}" target="_blank" rel="noreferrer">{label}</a></td>'


def _table_html(df):
    cols = ["name", "province", "software", "category", "website", "final_url", "source_url"]
    cols = [c for c in cols if c in df.columns]
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r.get(c, "")
            if c == "source_url":
                cells.append(_source_cell(v))
            elif c in ("website", "final_url") and v and str(v).startswith("http"):
                cells.append(f'<td><a href="{v}" target="_blank" rel="noreferrer">{v[:60]}</a></td>')
            else:
                cells.append(f"<td>{v if pd.notna(v) else ''}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    col_headers = [c if c != "source_url" else "source" for c in cols]
    header = "".join(f"<th>{c}</th>" for c in col_headers)
    return f"""
<div class="table-wrap">
<input type="text" id="tableSearch" placeholder="Search clubs…" oninput="filterTable()" />
<table id="clubTable">
  <thead><tr>{header}</tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>
<script>
function filterTable() {{
  const q = document.getElementById('tableSearch').value.toLowerCase();
  document.querySelectorAll('#clubTable tbody tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
"""


_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Canadian Swim Club Software Survey</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #f5f7fa; color: #1e293b; }
  header { background: #1e3a5f; color: #fff; padding: 1.5rem 2rem; }
  header h1 { font-size: 1.6rem; }
  header p { margin-top: .4rem; font-size: .9rem; opacity: .8; }
  main { max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }
  .stats { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 2rem; }
  .stat-card { background: #fff; border-radius: 8px; padding: 1rem 1.5rem;
               box-shadow: 0 1px 3px #0001; flex: 1; min-width: 140px; }
  .stat-card .val { font-size: 2rem; font-weight: 700; color: #2563EB; }
  .stat-card .lbl { font-size: .8rem; color: #64748b; margin-top: .2rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
          gap: 1.5rem; margin-bottom: 2rem; }
  .chart-card { background: #fff; border-radius: 8px; padding: 1.5rem;
                box-shadow: 0 1px 3px #0001; }
  .chart-card canvas { max-height: 420px; }
  h2 { font-size: 1.2rem; margin-bottom: 1rem; color: #1e3a5f; }
  .table-wrap { background: #fff; border-radius: 8px; padding: 1.5rem;
                box-shadow: 0 1px 3px #0001; overflow-x: auto; margin-bottom: 3rem; }
  #tableSearch { width: 100%; padding: .5rem .75rem; border: 1px solid #cbd5e1;
                 border-radius: 6px; margin-bottom: 1rem; font-size: .9rem; }
  table { border-collapse: collapse; width: 100%; font-size: .82rem; }
  th { background: #1e3a5f; color: #fff; padding: .5rem .75rem; text-align: left;
       position: sticky; top: 0; }
  td { padding: .4rem .75rem; border-bottom: 1px solid #f1f5f9; }
  tr:hover td { background: #f8fafc; }
  a { color: #2563EB; }
  footer { border-top: 1px solid #e2e8f0; margin-top: 1rem; }
  /* HTML horizontal bar chart */
  .hbar-card { grid-column: 1 / -1; }
  .hbar-title { font-size: 1rem; font-weight: 600; color: #1e3a5f; margin-bottom: .2rem; }
  .hbar-subtitle { font-size: .75rem; color: #94a3b8; margin-bottom: 1rem; }
  .hbar-chart { display: flex; flex-direction: column; gap: .45rem; }
  .hbar-row { display: flex; align-items: center; gap: .75rem; }
  .hbar-label { flex: 0 0 190px; text-align: right; font-size: .85rem; white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; }
  .sw-link { color: #2563EB; text-decoration: none; font-weight: 500; }
  .sw-link:hover { text-decoration: underline; }
  .sw-nolink { color: #475569; }
  .hbar-track { flex: 1; background: #f1f5f9; border-radius: 4px; height: 26px;
                overflow: hidden; }
  .hbar-fill { height: 100%; border-radius: 4px; display: flex; align-items: center;
               min-width: 2rem; transition: width .3s ease; }
  .hbar-count { padding: 0 .5rem; font-size: .78rem; font-weight: 600; color: #fff;
                white-space: nowrap; }
</style>
</head>
<body>
"""


def generate_html(df, output_path):
    pal = _platform_colours(df["software"].unique())

    charts_html = ""

    # Chart 1: overall — HTML bar chart so platform names are real links
    charts_html += _overall_chart_html(df)

    # Chart 2: category doughnut
    cfg = _category_chart(df)
    charts_html += _CHART_TEMPLATE.format(
        cid="category", cfg=json.dumps(cfg)
    )

    # Chart 3: province stacked
    cfg = _province_stacked_chart(df, pal)
    charts_html += _CHART_TEMPLATE.format(
        cid="province_stacked", cfg=json.dumps(cfg)
    )

    # Chart 4: top per province grouped
    cfg = _top_per_province_chart(df, pal)
    charts_html += _CHART_TEMPLATE.format(
        cid="province_grouped", cfg=json.dumps(cfg)
    )

    # Chart 5: size buckets (optional)
    cfg = _size_chart(df)
    if cfg:
        charts_html += _CHART_TEMPLATE.format(
            cid="size_chart", cfg=json.dumps(cfg)
        )

    # Summary stats
    total = len(df)
    provinces = df["province"].nunique()
    platforms = df["software"].nunique()
    _sw_counts = (
        df[~df["software"].isin(_EXCLUDE_FROM_DISTRIBUTION)]["software"]
        .value_counts()
    )
    top_platform = _sw_counts.idxmax() if not _sw_counts.empty else "—"

    stats_html = f"""
<div class="stats">
  <div class="stat-card"><div class="val">{total}</div><div class="lbl">Clubs surveyed</div></div>
  <div class="stat-card"><div class="val">{provinces}</div><div class="lbl">Provinces / territories</div></div>
  <div class="stat-card"><div class="val">{platforms}</div><div class="lbl">Distinct platforms found</div></div>
  <div class="stat-card"><div class="val">{top_platform}</div><div class="lbl">Most common platform</div></div>
</div>
"""

    disclaimer_html = ""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        error_count = int(df["error"].notna().sum())
        disclaimer_html = (
            f'<p style="margin-top:.4rem;font-size:.8rem;opacity:.65;">'
            f"This report was generated automatically via GitHub Actions "
            f"({error_count} clubs returned errors). Automated runs may have a higher "
            f"error rate than locally generated results due to network restrictions "
            f"and IP blocking by some club websites.</p>"
        )

    html = (
        _HTML_HEAD
        + f"""
<header>
  <h1>Canadian Swim Club — Team Management Software Survey</h1>
  <p>Automated survey of swimming.ca-registered clubs and provincial associations</p>
  <p style="margin-top:.6rem;font-size:.8rem;opacity:.65;">
    Club list sourced from the Swimming Canada national feed and several
    <a href="https://github.com/swimblocks/swim-club-tech-survey/blob/main/docs/data_sources.md"
       target="_blank" rel="noreferrer" style="color:#93c5fd;">provincial directories</a>.
  </p>
  {disclaimer_html}
</header>
<main>
{stats_html}
<h2>Charts</h2>
<div class="grid">
{charts_html}
</div>
<h2>Full data</h2>
<div style="margin-bottom:.75rem;">
  <a href="https://github.com/swimblocks/swim-club-tech-survey/releases/latest/download/results.csv"
     style="display:inline-block;padding:.4rem .9rem;background:#2563EB;color:#fff;border-radius:6px;font-size:.85rem;text-decoration:none;font-weight:500;">
    &#8595; Download CSV
  </a>
</div>
{_table_html(df)}
</main>
<footer style="text-align:center;padding:1.5rem;font-size:.8rem;color:#94a3b8;">
  <a href="https://github.com/swimblocks/swim-club-tech-survey/releases/latest"
     target="_blank" rel="noreferrer">Release notes &amp; past datasets</a>
</footer>
</body>
</html>
"""
    )

    Path(output_path).write_text(html, encoding="utf-8")
    return output_path
