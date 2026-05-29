"""
main.py — orchestrator for the Canadian swim-club software survey.

Usage:
    python main.py [--limit N] [--no-cache] [--delay SECS]

Steps:
  1. Fetch club list from Swimming Canada (REST API + HTML fallback)
     and provincial association websites
  2. Visit each club's website and detect team management software
  3. Save raw results to data/clubs_raw.csv
  4. Save enriched results to data/results.csv
  5. Generate output/report.html with Chart.js visualisations
  6. Write output/RUN_INFO.md with execution timestamp and summary stats

Club-list management flags (do not run the full survey):
    --refresh-clubs   Re-fetch live and update data/clubs.json.  If any club names
                      look like typos with no saved resolution, their records are
                      written to data/clubs_suspects.json and the run exits 2.
    --apply-suspects  Merge resolved suspects from data/clubs_suspects.json into
                      data/clubs.json using saved data/name_resolutions.json
                      (no re-scraping).
"""

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from src.clubs import apply_suspects, fetch_all_clubs
from src.name_resolution import UnresolvedSuspectError
from src.classify import reclassify
from src.detector import detect
from src.visualize import generate_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
RAW_CSV = DATA_DIR / "clubs_raw.csv"
RESULTS_CSV = DATA_DIR / "results.csv"
REPORT_HTML = OUTPUT_DIR / "report.html"
RUN_INFO_MD = OUTPUT_DIR / "RUN_INFO.md"

# Fields retained in published output — city, lat, lng are excluded to avoid
# republishing address-level data from the Swimming Canada directory.
_OUTPUT_FIELDS = [
    "name", "province", "province_name",
    "website", "software", "category", "final_url", "error", "source_url",
]


def _load_cached():
    if RESULTS_CSV.exists():
        df = pd.read_csv(RESULTS_CSV)
        log.info("Loaded %d cached results from %s", len(df), RESULTS_CSV)
        return df
    return None


def _save_raw(clubs):
    DATA_DIR.mkdir(exist_ok=True)
    fieldnames = ["name", "province", "province_name", "website", "source"]
    with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(clubs)
    log.info("Saved raw club list → %s", RAW_CSV)


def _save_results(rows):
    DATA_DIR.mkdir(exist_ok=True)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_OUTPUT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("Saved enriched results → %s", RESULTS_CSV)


def _write_run_info(df, ran_at):
    total = len(df)
    with_site = df["website"].notna().sum()
    dist = df["software"].value_counts()
    top = dist[~dist.index.isin({"No Website", "Error"})].head(5)

    lines = [
        "# Survey Run Info",
        "",
        f"**Last executed:** {ran_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Clubs surveyed:** {total}",
        f"**Clubs with websites:** {int(with_site)}",
        "",
        "**Top platforms:**",
        "",
    ]
    for name, count in top.items():
        lines.append(f"- {name}: {count}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        error_count = int(df["error"].notna().sum())
        lines += [
            "",
            f"> **Note:** This run was generated automatically via GitHub Actions "
            f"({error_count} clubs returned errors). Automated runs may have a higher "
            f"error rate than locally generated results due to network restrictions "
            f"and IP blocking by some club websites.",
        ]

    lines += [
        "",
        "**Data sources:** Club list assembled from the national Swimming Canada feed "
        "and several provincial directories — see "
        "[docs/data_sources.md](https://github.com/swimblocks/swim-club-tech-survey/blob/main/docs/data_sources.md) "
        "for the full list.",
        "",
        "**Published results:** https://gavinbee.github.io/canada-swim-tech-survey/",
        "",
        "**How to reproduce:** `python main.py --no-cache`",
    ]
    RUN_INFO_MD.write_text("\n".join(lines), encoding="utf-8")
    log.info("Run info → %s", RUN_INFO_MD)


def run(limit=None, use_cache=True, extra_delay=0.0, refresh_clubs=False,
        apply_suspects_mode=False):
    OUTPUT_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)

    # ----------------------------------------------------------------
    # Club-list management modes — update clubs.json then exit
    # ----------------------------------------------------------------
    if apply_suspects_mode:
        log.info("=== Applying resolved suspects to data/clubs.json ===")
        added = apply_suspects()
        if added:
            log.info("Done. %d club(s) added — commit data/clubs.json and data/name_resolutions.json.", added)
        else:
            log.info("Done. No new clubs added (all suspects were skipped or already present).")
        return

    ran_at = datetime.now(timezone.utc)

    # ----------------------------------------------------------------
    # Step 1: fetch clubs
    # ----------------------------------------------------------------
    log.info("=== Step 1: Fetching club list ===")
    try:
        clubs = fetch_all_clubs(force_refresh=refresh_clubs)
    except UnresolvedSuspectError as exc:
        log.error(
            "Club refresh halted: %d club name(s) had suspected typos with no saved "
            "resolution: %s. Add resolutions to data/name_resolutions.json, then "
            "re-run --refresh-clubs or run --apply-suspects.",
            len(exc.names), exc.names,
        )
        sys.exit(2)

    if not clubs:
        log.error("No clubs found — check network access and Swimming Canada website.")
        sys.exit(1)

    _save_raw(clubs)

    if limit:
        clubs = clubs[:limit]
        log.info("Limiting to first %d clubs for this run", limit)

    # ----------------------------------------------------------------
    # Step 2: software detection
    # ----------------------------------------------------------------
    if use_cache and RESULTS_CSV.exists():
        df = _load_cached()
        done = set(df["website"].dropna().str.rstrip("/").str.lower())
        remaining = [c for c in clubs if c.get("website", "").rstrip("/").lower() not in done]
        rows = df.to_dict("records")
    else:
        remaining = clubs
        rows = []

    log.info("=== Step 2: Detecting software for %d clubs ===", len(remaining))

    for club in tqdm(remaining, unit="club", desc="Scanning"):
        if extra_delay:
            time.sleep(extra_delay)
        result = detect(club.get("website", ""))
        row = {**club, **result}
        rows.append(row)
        _save_results(rows)

    # ----------------------------------------------------------------
    # Step 3: reporting
    # ----------------------------------------------------------------
    log.info("=== Step 3: Generating report ===")
    df = pd.read_csv(RESULTS_CSV)

    df["software"] = df["software"].fillna("Unknown / Custom")
    df["category"] = df["category"].fillna("Unknown / Custom")
    df["province"] = df["province"].str.upper().str.strip()

    df = reclassify(df)

    # Persist the reclassified data
    df[_OUTPUT_FIELDS].to_csv(RESULTS_CSV, index=False)

    generate_html(df, REPORT_HTML)
    _write_run_info(df, ran_at)

    log.info("Report → %s", REPORT_HTML)
    log.info("Done. %d clubs processed.", len(df))

    summary = df["software"].value_counts().reset_index()
    summary.columns = ["Software", "Clubs"]
    print("\n=== Software distribution ===")
    print(summary.to_string(index=False))


# -------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Canadian swim-club software survey")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Process only the first N clubs (useful for testing)"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Ignore cached results.csv and re-scan everything"
    )
    parser.add_argument(
        "--delay", type=float, default=0.0,
        help="Extra delay in seconds between requests (on top of built-in politeness delay)"
    )
    parser.add_argument(
        "--refresh-clubs", action="store_true",
        help="Re-fetch the club list from all sources and update data/clubs.json. "
             "If any club names look like typos with no saved resolution, their records "
             "are written to data/clubs_suspects.json and the run exits 2."
    )
    parser.add_argument(
        "--apply-suspects", action="store_true",
        help="Merge resolved suspects from data/clubs_suspects.json into data/clubs.json "
             "using saved data/name_resolutions.json (no re-scraping)."
    )
    args = parser.parse_args()

    run(
        limit=args.limit,
        use_cache=not args.no_cache,
        extra_delay=args.delay,
        refresh_clubs=args.refresh_clubs,
        apply_suspects_mode=args.apply_suspects,
    )
