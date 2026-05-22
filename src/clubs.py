"""
Club discovery: fetches Canadian swim clubs from Swimming Canada's
club-list API at swimming.ca/club-list.php (returns JSONP).

Derives province from the postal code in each club's address field.
Returns a list of dicts: name, province, province_name, city, website, members, source.
"""

import json
import logging
import re
import time
import warnings
from pathlib import Path

import requests
import urllib3

from src.name_resolution import UnresolvedSuspectError, _load_resolutions, _resolve_name

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    # club-list.php is loaded by JS on findaclub.swimming.ca — the server
    # checks Referer to block direct non-browser requests
    "Referer": "https://findaclub.swimming.ca/",
    "Accept": "text/javascript, application/javascript, */*",
    "Accept-Language": "en-CA,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

CLUB_LIST_URL = "https://www.swimming.ca/club-list.php"

# First letter of Canadian postal code → province code
_POSTAL_TO_PROV = {
    "A": "NL",
    "B": "NS",
    "C": "PE",
    "E": "NB",
    "G": "QC",
    "H": "QC",
    "J": "QC",
    "K": "ON",
    "L": "ON",
    "M": "ON",
    "N": "ON",
    "P": "ON",
    "R": "MB",
    "S": "SK",
    "T": "AB",
    "V": "BC",
    "X": "NT",
    "Y": "YT",
}

PROVINCE_NAMES = {
    "BC": "British Columbia",
    "AB": "Alberta",
    "SK": "Saskatchewan",
    "MB": "Manitoba",
    "ON": "Ontario",
    "QC": "Quebec",
    "NB": "New Brunswick",
    "NS": "Nova Scotia",
    "PE": "Prince Edward Island",
    "NL": "Newfoundland and Labrador",
    "YT": "Yukon",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
}

_POSTAL_RE = re.compile(r"([A-Z])\d[A-Z]\s*\d[A-Z]\d", re.I)
_CITY_RE = re.compile(r"^(.+?)\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d", re.I)


def _province_from_address(address):
    m = _POSTAL_RE.search(address)
    if m:
        return _POSTAL_TO_PROV.get(m.group(1).upper(), "")
    return ""


def _city_from_address(address):
    m = _CITY_RE.search(address)
    if m:
        return m.group(1).strip()
    return ""


SNAPSHOT_PATH = Path(__file__).parent.parent / "data" / "clubs.json"
SUSPECTS_PATH = Path(__file__).parent.parent / "data" / "clubs_suspects.json"

# Websites and names that belong to governing bodies, officials registrations,
# or other non-club entries. Extend these sets when new non-club entries appear.
_EXCLUDED_WEBSITES = {
    "https://www.csca.org",  # Canadian Swimming Coaches Association — not a club
}

_EXCLUDED_NAMES = {
    "Officials Registration ON",  # Swim Ontario officials registration — not a club
}

# Provincial sources: (province_code, scraper_type, url)
_PROVINCIAL_SOURCES = [
    ("ON", "gatsby_json",      "https://www.swimontario.com/page-data/clubs/find-a-club/page-data.json"),
    ("BC", "html_table_bc",    "https://swimbc.ca/clubs/how-to-join-a-swim-club/"),
    ("AB", "html_divs_ab",     "https://swimalberta.ca/community/clubs/find-a-club/"),
    ("MB", "html_table_mb",    "https://swimmanitoba.mb.ca/clubs/"),
    ("NL", "html_pdf_links_nl","https://swimmingnl.ca/directory"),
]


def fetch_all_clubs(force_refresh=False):
    """
    Return Canadian swim club dicts ready for software detection.

    Tries the live Swimming Canada API first.  If that fails (e.g. the
    server blocks cloud IP ranges such as GitHub Actions), falls back to
    the committed snapshot at data/clubs.json.

    Supplements the Swimming Canada list with provincial association
    directories to catch clubs not registered nationally.

    Pass force_refresh=True (or run main.py --refresh-clubs) to skip the
    snapshot and always hit the live APIs, then save a new snapshot.

    If any club names look like typos and have no saved resolution in
    data/name_resolutions.json, their full scraped records are written to
    data/clubs_suspects.json and UnresolvedSuspectError is raised (exit 2).
    Add resolutions to name_resolutions.json, then re-run --refresh-clubs or
    run --apply-suspects to merge the saved records without re-scraping.
    """
    if not force_refresh and SNAPSHOT_PATH.exists():
        return _filter_clubs(_load_snapshot())

    unresolved: list[str] = []
    suspects_out: list[dict] = []
    clubs = _fetch_live()
    if clubs:
        clubs = _merge_provincial(clubs, unresolved, suspects_out)
        clubs = _filter_clubs(clubs)
        _save_snapshot(clubs)
        if suspects_out:
            _save_suspects(suspects_out)
            log.warning(
                "%d suspect name(s) saved to %s — add resolutions to "
                "data/name_resolutions.json, then re-run --refresh-clubs "
                "or run --apply-suspects",
                len(suspects_out), SUSPECTS_PATH,
            )
        if unresolved:
            raise UnresolvedSuspectError(unresolved)
        return clubs

    # Live fetch failed — fall back to snapshot
    if SNAPSHOT_PATH.exists():
        log.warning("Live fetch failed; using committed snapshot %s", SNAPSHOT_PATH)
        return _filter_clubs(_load_snapshot())

    return []


def apply_suspects() -> int:
    """
    Read data/clubs_suspects.json, apply saved name_resolutions.json, and
    merge resolved clubs into data/clubs.json.  Deletes clubs_suspects.json
    on success.  Returns the number of clubs added.

    Run this after --detect-suspects has saved suspects and you have updated
    data/name_resolutions.json (either manually or via --refresh-clubs on an
    interactive terminal).
    """
    if not SUSPECTS_PATH.exists():
        log.info("No suspects file at %s — nothing to apply", SUSPECTS_PATH)
        return 0

    with open(SUSPECTS_PATH, encoding="utf-8") as f:
        suspects = json.load(f)

    if not suspects:
        SUSPECTS_PATH.unlink()
        return 0

    resolutions = _load_resolutions()
    clubs = _load_snapshot() if SNAPSHOT_PATH.exists() else []
    existing_names = {c["name"].lower() for c in clubs}
    existing_sites = {c["website"].lower() for c in clubs if c["website"]}

    added = 0
    for suspect in suspects:
        original_name = suspect["name"]
        entry = resolutions.get(original_name)
        if not entry:
            log.warning("No resolution saved for %r — skipping (add to name_resolutions.json)", original_name)
            continue
        action = entry.get("action")
        if action == "skip":
            log.info("Skipping %r per saved resolution", original_name)
            continue
        resolved_name = entry["to"] if action == "rename" else original_name

        name_key = resolved_name.lower()
        site_key = suspect["website"].lower() if suspect.get("website") else None
        if name_key in existing_names:
            log.info("Skipping %r — already in clubs.json", resolved_name)
            continue
        if site_key and site_key in existing_sites:
            log.info("Skipping %r — website already in clubs.json", resolved_name)
            continue

        clubs.append({**suspect, "name": resolved_name})
        existing_names.add(name_key)
        if site_key:
            existing_sites.add(site_key)
        added += 1

    if added:
        _save_snapshot(clubs)
        log.info("Added %d resolved club(s) → %s", added, SNAPSHOT_PATH)

    SUSPECTS_PATH.unlink()
    log.info("Removed suspects file %s", SUSPECTS_PATH)
    return added


def _filter_clubs(clubs):
    """Remove known non-club entries (governing bodies, officials registrations, etc.)."""
    filtered = [
        c for c in clubs
        if c.get("website", "") not in _EXCLUDED_WEBSITES
        and c.get("name", "") not in _EXCLUDED_NAMES
    ]
    removed = len(clubs) - len(filtered)
    if removed:
        log.info("Excluded %d non-club entries", removed)
    return filtered


def _normalise_website(url):
    if not url:
        return ""
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    if "facebook.com" in url:
        return ""
    return url


def _save_suspects(suspects: list[dict]) -> None:
    SUSPECTS_PATH.parent.mkdir(exist_ok=True)
    with open(SUSPECTS_PATH, "w", encoding="utf-8") as f:
        json.dump(suspects, f, indent=2, ensure_ascii=False)


def _merge_provincial(clubs, unresolved, suspects_out=None):
    """Fetch each known provincial directory and add clubs missing from the national list."""
    existing_by_name = {c["name"].lower(): c for c in clubs}
    existing_names = set(existing_by_name)
    existing_sites = {c["website"].lower() for c in clubs if c["website"]}

    added = 0
    for province, scraper, url in _PROVINCIAL_SOURCES:
        provincial = _fetch_provincial(province, scraper, url, unresolved, suspects_out)
        for club in provincial:
            name_key = club["name"].lower()
            site_key = club["website"].lower() if club["website"] else None
            if name_key in existing_names:
                existing = existing_by_name[name_key]
                if not existing.get("website") and club.get("website"):
                    existing["website"] = club["website"]
                    existing["source_url"] = club.get("source_url", existing.get("source_url", ""))
                    existing_sites.add(site_key)
                continue
            if site_key and site_key in existing_sites:
                continue
            clubs.append(club)
            existing_by_name[name_key] = club
            existing_names.add(name_key)
            if site_key:
                existing_sites.add(site_key)
            added += 1

    if added:
        log.info("Added %d clubs from provincial directories", added)
    return clubs


def _fetch_provincial(province, scraper, url, unresolved, suspects_out=None):
    log.info("Fetching provincial club list (%s): %s", province, url)
    ua = {"User-Agent": HEADERS["User-Agent"]}
    try:
        r = requests.get(url, headers=ua, timeout=20, verify=False)
        r.raise_for_status()
    except Exception as exc:
        log.warning("Provincial fetch failed (%s): %s", province, exc)
        return []

    if scraper == "gatsby_json":
        return _parse_gatsby_json(province, r, unresolved, suspects_out)
    if scraper == "html_table_bc":
        return _parse_bc_table(province, r, source_url=url, unresolved=unresolved, suspects_out=suspects_out)
    if scraper == "html_table_mb":
        return _parse_mb_table(province, r, source_url=url, unresolved=unresolved, suspects_out=suspects_out)
    if scraper == "html_divs_ab":
        return _parse_ab_divs(province, r, source_url=url, unresolved=unresolved, suspects_out=suspects_out)
    if scraper == "html_pdf_links_nl":
        return _parse_nl_pdfs(province, r, source_url=url, unresolved=unresolved, suspects_out=suspects_out)

    log.warning("Unknown provincial scraper type: %s", scraper)
    return []


def _make_club(name, website, province, postal="", source_url="", unresolved=None, suspects_out=None):
    _unresolved = unresolved if unresolved is not None else []
    prev_len = len(_unresolved)
    resolved_name, skip = _resolve_name(name, _unresolved)
    if skip:
        if suspects_out is not None and len(_unresolved) > prev_len:
            # Unresolved suspect in detect mode — save full record for --apply-suspects
            prov = _province_from_address(postal) or province
            suspects_out.append({
                "name": name,
                "province": prov,
                "province_name": PROVINCE_NAMES.get(prov, prov),
                "website": _normalise_website(website),
                "source_url": source_url,
            })
        return None
    prov = _province_from_address(postal) or province
    return {
        "name": resolved_name,
        "province": prov,
        "province_name": PROVINCE_NAMES.get(prov, prov),
        "website": _normalise_website(website),
        "source_url": source_url,
    }


_SWIMONTARIO_BASE = "https://www.swimontario.com/clubs/find-a-club/"


def _parse_gatsby_json(province, r, unresolved, suspects_out=None):
    try:
        data = r.json()
        children = data["result"]["data"]["wagtail"]["page"]["children"]
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("Gatsby JSON parse failed (%s): %s", province, exc)
        return []
    clubs = []
    for item in children:
        name = (item.get("name") or "").strip()
        slug = (item.get("slug") or "").strip()
        source_url = f"{_SWIMONTARIO_BASE}{slug}/" if slug else _SWIMONTARIO_BASE
        if name:
            club = _make_club(name, item.get("website") or "", province,
                              item.get("postalcode") or "", source_url=source_url,
                              unresolved=unresolved, suspects_out=suspects_out)
            if club:
                clubs.append(club)
    log.info("Fetched %d clubs from Gatsby JSON (%s)", len(clubs), province)
    return clubs


def _parse_bc_table(province, r, source_url="", unresolved=None, suspects_out=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table")
    if not table:
        log.warning("BC table not found")
        return []
    clubs = []
    for row in table.find_all("tr")[1:]:  # skip header
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        name = cells[1].get_text(strip=True)
        links = [a["href"] for a in row.find_all("a", href=True)
                 if a["href"].startswith("http") and "google" not in a["href"]
                 and "facebook" not in a["href"]]
        if name:
            club = _make_club(name, links[0] if links else "", province,
                              source_url=source_url, unresolved=unresolved, suspects_out=suspects_out)
            if club:
                clubs.append(club)
    log.info("Fetched %d clubs from BC table", len(clubs))
    return clubs


def _parse_mb_table(province, r, source_url="", unresolved=None, suspects_out=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    table = soup.find("table")
    if not table:
        log.warning("MB table not found")
        return []
    clubs = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        name = cells[0].get_text(strip=True)
        links = [a["href"] for a in row.find_all("a", href=True)
                 if a["href"].startswith("http") and "google" not in a["href"]
                 and "facebook" not in a["href"]]
        if name:
            club = _make_club(name, links[0] if links else "", province,
                              source_url=source_url, unresolved=unresolved, suspects_out=suspects_out)
            if club:
                clubs.append(club)
    log.info("Fetched %d clubs from MB table", len(clubs))
    return clubs


def _parse_ab_divs(province, r, source_url="", unresolved=None, suspects_out=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    clubs = []
    for div in soup.find_all("div", class_="club_directory_col"):
        text = div.get_text(separator="|", strip=True)
        m = re.search(r"Club Name:\|([^|]+)", text)
        name = m.group(1).strip() if m else ""
        links = [a["href"] for a in div.find_all("a", href=True)
                 if a["href"].startswith("http") and "google" not in a["href"]
                 and "facebook" not in a["href"] and "swimalberta" not in a["href"]]
        if name:
            club = _make_club(name, links[0] if links else "", province,
                              source_url=source_url, unresolved=unresolved, suspects_out=suspects_out)
            if club:
                clubs.append(club)
    log.info("Fetched %d clubs from AB divs", len(clubs))
    return clubs


_NL_EXCLUDE_NAMES = {"swimming nl executive"}


def _parse_nl_pdfs(province, r, source_url="", unresolved=None, suspects_out=None):
    """Parse the Swimming NL directory page (GoDaddy site).

    Each club is listed as a PDF download link.  The anchor text contains the
    club name with a trailing suffix like " 2025-26(pdf)Download" that is
    stripped.  Each PDF may contain a "Club Website" field; "N/A" values are
    treated as no website.
    """
    from bs4 import BeautifulSoup
    import io
    import pdfplumber

    soup = BeautifulSoup(r.text, "lxml")
    clubs = []
    ua = {"User-Agent": HEADERS["User-Agent"]}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"\.pdf", href, re.I):
            continue
        raw_text = a.get_text(separator=" ", strip=True)
        # Strip trailing download/year suffix: " 2025-26(pdf)Download", "(pdf)Download", etc.
        name = re.sub(r"\s*\d{4}[-–]\d{2,4}\s*\(pdf\)\s*download\s*$", "", raw_text, flags=re.I).strip()
        name = re.sub(r"\s*\(pdf\)\s*download\s*$", "", name, flags=re.I).strip()
        if not name or name.lower() in _NL_EXCLUDE_NAMES:
            continue

        website = ""
        try:
            if href.startswith("//"):
                href = "https:" + href
            pdf_resp = requests.get(href, headers=ua, timeout=20, verify=False)
            pdf_resp.raise_for_status()
            with pdfplumber.open(io.BytesIO(pdf_resp.content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            m = re.search(r"Club Website[ \t]+([^\n]+)", text)
            if m:
                candidate = m.group(1).strip()
                if candidate.lower() not in ("n/a", "", "none"):
                    website = candidate
        except Exception as exc:
            log.debug("NL PDF fetch/parse failed for %s: %s", name, exc)

        club = _make_club(name, website, province, source_url=source_url,
                          unresolved=unresolved, suspects_out=suspects_out)
        if club:
            clubs.append(club)

    log.info("Fetched %d clubs from NL PDF links", len(clubs))
    return clubs


def _fetch_live():
    log.info("Fetching club list from %s", CLUB_LIST_URL)
    try:
        r = requests.get(
            CLUB_LIST_URL,
            headers=HEADERS,
            timeout=20,
            params={"preview": "true"},
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Live club-list fetch failed: %s", exc)
        return []

    text = r.text.strip()
    if text.startswith("load_clubs("):
        text = text[len("load_clubs("):]
        if text.endswith(")"):
            text = text[:-1]
    elif text.startswith("("):
        text = text[1:-1]

    try:
        raw = json.loads(text)
    except ValueError as exc:
        log.warning("JSON parse error: %s", exc)
        return []

    clubs = []
    seen = set()
    for item in raw:
        name = item.get("name", "").strip()
        address = item.get("address", "")
        website_clean = _normalise_website(item.get("website") or "")
        province = _province_from_address(address)

        key = (name.lower(), website_clean.lower())
        if key in seen:
            continue
        seen.add(key)

        clubs.append({
            "name": name,
            "province": province,
            "province_name": PROVINCE_NAMES.get(province, province),
            "website": website_clean,
            "source_url": "https://findaclub.swimming.ca/",
        })

    log.info("Fetched %d clubs live (%d with websites)", len(clubs),
             sum(1 for c in clubs if c["website"]))
    return clubs


def _load_snapshot():
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        clubs = json.load(f)
    log.info("Loaded %d clubs from snapshot %s", len(clubs), SNAPSHOT_PATH)
    return clubs


def _save_snapshot(clubs):
    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    snapshot = [
        {"name": c["name"], "province": c["province"],
         "province_name": c["province_name"], "website": c["website"],
         "source_url": c.get("source_url", "")}
        for c in clubs
    ]
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    log.info("Saved club snapshot → %s", SNAPSHOT_PATH)
