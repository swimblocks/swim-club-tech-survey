# Canadian Swim Club Software Survey

Automatically discovers every Swimming Canada–registered club, visits their website,
and detects tech stack information for the club.  Currently, primarily focused on which team 
management / registration platform a club uses.

Results are saved to CSV and rendered as an interactive HTML report with Chart.js bar graphs.

Club list sourced from the [Swimming Canada public club directory](https://www.swimming.ca).
Individual club addresses are not stored or published.

**[View latest report](https://swimblocks.github.io/swim-club-tech-survey/) · [Download past datasets](../../releases)**

---

## How it works

```
Swimming Canada REST API  ─┐
Swimming Canada HTML       ├─ src/clubs.py ──▶ raw club list (name, province, city, website)
Provincial association     ┘                      │
websites (BC, AB, SK, …)                          │
                                                  ▼
                                         src/detector.py
                                    (visit each website, match
                                     platform signatures)
                                                  │
                                                  ▼
                                    data/results.csv  +  output/report.html
```

### 1 — Club discovery (`src/clubs.py`)

Starts with the Swimming Canada national club-list API (JSONP), then supplements
with provincial association directories for BC, AB, MB, ON, and NL to capture clubs
not registered nationally. Results are deduplicated on name and website URL.

**Name-typo detection** (`src/name_resolution.py`): each scraped club name is checked
against a vocabulary of common swim-club words. Suspected typos are resolved using
`data/name_resolutions.json` (committed to the repo). Interactive runs (`--refresh-clubs`
in a terminal) prompt for a decision; non-interactive runs (CI) skip the suspect and
raise `UnresolvedSuspectError`, exiting with code 2 so the workflow fails visibly.

See [`docs/club_discovery.md`](docs/club_discovery.md) for the complete source
inventory, data formats, implementation status for each province, and a full
description of the name-resolution system.

### 2 — Software detection (`src/detector.py`)

For each club website:

| Check | What is inspected |
|---|---|
| Final URL after redirects | Some clubs' site *is* the platform (e.g. `myclub.teamunify.com`) |
| All `href` / `src` / `action` / `data-src` attributes | Catches CDN URLs, registration iframe sources, API calls |
| Full HTML source (regex) | `Powered by …`, generator meta tags, inline script references |
| HTTP response headers | `X-Powered-By`, `X-Generator`, `X-Wix-*`, etc. |

Platforms detected:

**Swim-specific**
TeamUnify · Amilia · Uplifter · Club Assistant · SwimTopia · Swimmingly · Webpoint · Swim Canada Online · Commit

**General sports management**
SportsEngine · TeamSnap · Jackrabbit · iClass Pro · Sporty HQ · Active Network · Regatta Network · rTeam · FinalForms

**CMS / Website builders**
WordPress · Wix · Squarespace · Weebly · Google Sites · Jimdo · Webflow · Drupal · Joomla

Falls back to **"Unknown / Custom"** when no signature matches.

### 3 — Report generation (`src/visualize.py`)

Reads `data/results.csv` and produces `output/report.html` — a single self-contained file
with Chart.js loaded from CDN. Charts:

1. **Overall software distribution** — horizontal bar sorted by club count
2. **Category breakdown** — doughnut (swim-specific vs sports-management vs CMS)
3. **Software by province (stacked bar)** — each province stacked by platform
4. **Top 10 platforms by province (grouped bar)** — easier to compare within a province
5. **Software by club size** — stacked bar bucketed by registered swimmer count (if data available)

Plus a searchable full-data table at the bottom.

---

## Quick start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the survey (may take 20–60 min for ~600+ clubs)
python main.py

# Test with just the first 20 clubs
python main.py --limit 20

# Re-scan everything, ignoring the cached CSV
python main.py --no-cache

# Add 0.5 s extra delay between requests (polite crawling)
python main.py --delay 0.5
```

#### Updating the club list

```bash
# Re-fetch all sources and update data/clubs.json.
# If any club names look like typos with no saved resolution, their records are
# written to data/clubs_suspects.json and the run exits 2.
python main.py --refresh-clubs

# After adding resolutions to data/name_resolutions.json, merge the saved
# suspect records into clubs.json without re-scraping:
python main.py --apply-suspects
```

See [`docs/club_discovery.md`](docs/club_discovery.md) for details on name-typo
detection, the resolution file format, and how `--apply-suspects` works.

Outputs:
- `data/clubs_raw.csv` — club list before detection
- `data/results.csv` — full enriched dataset
- `output/report.html` — open in any browser

---

## Project layout

```
canada-swim-tech-survey/
├── main.py              Entry point / orchestrator
├── src/
│   ├── clubs.py             Club discovery (Swimming Canada + provincial)
│   ├── name_resolution.py   Club name typo detection and interactive resolution
│   ├── detector.py          Website → platform detection
│   └── visualize.py         CSV → HTML report with Chart.js
├── tests/               pytest test suite
├── docs/
│   ├── club_discovery.md  Per-province source inventory and scraper notes
│   └── data_sources.md    Active data sources (linked from report footer)
├── data/                CSV outputs (git-ignored except .gitkeep)
├── output/              HTML report (git-ignored except .gitkeep)
├── requirements.txt
└── README.md
```

---

## Limitations & caveats

- **robots.txt / rate limiting** — the scraper adds a ~1 s delay between requests
  and sends a realistic browser User-Agent, but some club sites may block automated
  access. Errors are recorded in the `error` column of the CSV.
- **Member counts** — "registered swimmers" data is only available when Swimming Canada
  exports it via their API; most clubs will show `null`. The size-bucket chart is
  suppressed when fewer than 5 clubs have this data.
- **Detection accuracy** — a club might embed a registration widget from one platform
  on a WordPress site; the tool reports the *first match* in priority order
  (swim-specific platforms are checked before generic CMS). Run `--no-cache` to refresh
  after updating signatures.
- **Swimming Canada API stability** — the API URL may change when the site is rebuilt.
  Adjust `CLUB_LIST_URL` in `src/clubs.py` if needed.
