"""
Software detection: visits each club website and identifies which team
management / registration platform powers it.

Detection strategy (in order):
  1. Follow HTTP redirects – some clubs' URLs *are* the platform (e.g. teamunify subdomain)
  2. Scan all <script src>, <link href>, <a href> and <form action> attributes
  3. Scan visible page text for "Powered by …" and "Register …" phrases
  4. Check <meta name="generator"> and <meta name="application-name">
  5. Inspect response headers (X-Powered-By, Server)

Returns one of the known platform keys or "Unknown / Custom" / "No Website".
"""

import logging
import re
import time
from urllib.parse import urlparse, urljoin

import warnings

import requests
import urllib3
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-CA,en;q=0.9",
}

REQUEST_DELAY = 1.0   # seconds between requests
TIMEOUT = 12          # seconds per request

# -------------------------------------------------------------------
# Platform signature definitions
#
# Each entry is a dict with:
#   "url_patterns"  – regexes matched against any URL found on the page
#                     (href, src, action, final redirect URL, etc.)
#   "text_patterns" – regexes matched against full page text / HTML source
#   "header_patterns" – regexes matched against response headers
#   "category"      – broad category for grouping in the report
# -------------------------------------------------------------------

PLATFORMS = {
    # ---- Swim-specific / Canadian-common ----
    # Commit Swimming — Canadian swim club platform (SPA hosted on Netlify;
    # detected via manifest.json which declares name "Commit Swimming")
    "Commit": {
        "url_patterns": [r"commitswimming\.com"],
        "text_patterns": [r"commit\s*swimming"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    # TeamUnify and GoMotion became SportsEngine Motion in November 2024.
    # Keep product-specific evidence ahead of SportsEngine HQ signatures.
    "SportsEngine Motion": {
        "url_patterns": [
            r"gomotionapp\.com", r"motion\.sportsengine\.com", r"teamunify\.com",
        ],
        "text_patterns": [
            r"sportsengine\s*motion", r"gomotionapp", r"gomotion", r"team\s*unify",
        ],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    # PoolQ is a Canadian swim club management SaaS
    "PoolQ": {
        "url_patterns": [r"poolq\.net"],
        "text_patterns": [r"poolq\.net"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    # JerseyWatch – sports club/team management (showed up in ~48 unknown sites)
    "JerseyWatch": {
        "url_patterns": [r"jerseywatch\.com"],
        "text_patterns": [r"jerseywatch"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # TeamLinkt – Canadian league/club management
    "TeamLinkt": {
        "url_patterns": [r"teamlinkt\.com"],
        "text_patterns": [r"teamlinkt"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # Sidearm Sports – university/college athletics platform
    "Sidearm Sports": {
        "url_patterns": [r"sidearmsports\.com"],
        "text_patterns": [r"sidearmsports", r"sidearm\s*sports"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # Presto Sports – another university athletics platform
    "Presto Sports": {
        "url_patterns": [r"prestosports\.com"],
        "text_patterns": [r"prestosports", r"presto\s*sports"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # GoalLine / Stack Sports – Canadian amateur sports web platform
    "GoalLine (Stack Sports)": {
        "url_patterns": [r"goalline\.ca", r"stacksports\.com"],
        "text_patterns": [r"goalline", r"stack\s*sports"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # Jonas Club Software – private-club / recreation-centre management
    "Jonas Club Software": {
        "url_patterns": [r"jonasclub\.com", r"jonas\s*software"],
        "text_patterns": [r"powered by jonas", r"jonas club software"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # GoDaddy Website Builder (Starfield Technologies)
    "GoDaddy Website Builder": {
        "url_patterns": [],
        "text_patterns": [r"starfield technologies.*go daddy website builder",
                          r"go daddy website builder",
                          r"godaddy.*website.*builder"],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
    # WebSelf.net – French-Canadian website builder
    "WebSelf": {
        "url_patterns": [r"webself\.net"],
        "text_patterns": [r"webself"],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
    # Duda – website builder used by agencies
    "Duda": {
        "url_patterns": [r"dudaone\.com", r"duda\.co"],
        "text_patterns": [r'"builder":"duda"', r"dudaone"],
        "header_patterns": [r"x-duda-"],
        "category": "CMS / Website builder",
    },
    "Amilia": {
        "url_patterns": [r"amilia\.com", r"app\.amilia\.com"],
        "text_patterns": [r"amilia"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "Uplifter": {
        "url_patterns": [r"uplifter\.ca", r"uplifter\.com"],
        "text_patterns": [r"uplifter"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "Club Assistant": {
        "url_patterns": [r"clubassistant\.com"],
        "text_patterns": [r"club\s*assistant"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "SwimTopia": {
        "url_patterns": [r"swimtopia\.com"],
        "text_patterns": [r"swimtopia"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "Swimmingly": {
        "url_patterns": [r"goswimmingly\.com", r"swimmingly\.com"],
        "text_patterns": [r"swimmingly"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "Webpoint": {
        "url_patterns": [r"webpoint\.us"],
        "text_patterns": [r"webpoint"],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    "Swim Canada Online": {
        "url_patterns": [r"swimming\.ca/registration"],
        "text_patterns": [],
        "header_patterns": [],
        "category": "Swim-specific",
    },
    # ---- General sports management ----
    "SportsEngine HQ": {
        "url_patterns": [
            r"sportsengine\.com/hq(?:[/?#]|$)", r"ngin\.com", r"sportsenginehq\.com",
        ],
        "text_patterns": [r"sportsengine\s*hq\b", r"ngin\.com"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "TeamSnap": {
        "url_patterns": [r"teamsnap\.com"],
        "text_patterns": [r"teamsnap"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "Jackrabbit": {
        "url_patterns": [r"jackrabbitclass\.com", r"app\.jackrabbitclass\.com"],
        "text_patterns": [r"jackrabbit\s*class", r"jackrabbittech"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "iClass Pro": {
        "url_patterns": [r"iclasspro\.com"],
        "text_patterns": [r"iclasspro"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "Sporty HQ": {
        "url_patterns": [r"sportyhq\.com"],
        "text_patterns": [r"sporty\s*hq"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "Active Network": {
        "url_patterns": [r"active\.com", r"activenetwork\.com", r"activegamesafe\.com"],
        "text_patterns": [r"active\s*network"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "Regatta Network": {
        "url_patterns": [r"regattanetwork\.com"],
        "text_patterns": [r"regatta\s*network"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "rTeam": {
        "url_patterns": [r"rteam\.com"],
        "text_patterns": [r"\brteam\b"],
        "header_patterns": [],
        "category": "Sports management",
    },
    "FinalForms": {
        "url_patterns": [r"finalforms\.com"],
        "text_patterns": [r"finalforms"],
        "header_patterns": [],
        "category": "Sports management",
    },
    # ---- General CMS / website builders ----
    "WordPress": {
        "url_patterns": [r"/wp-content/", r"/wp-includes/"],
        "text_patterns": [r"wp-content", r"wp-includes", r'"generator":"WordPress'],
        "header_patterns": [r"x-powered-by.*wordpress"],
        "category": "CMS / Website builder",
    },
    "Wix": {
        "url_patterns": [r"wix\.com", r"wixsite\.com", r"wixstatic\.com", r"static\.wixstatic"],
        "text_patterns": [r"wixsite\.com", r"x-wix-"],
        "header_patterns": [r"x-wix-"],
        "category": "CMS / Website builder",
    },
    "Squarespace": {
        "url_patterns": [r"squarespace\.com", r"sqsp\.net", r"squarecdn\.com"],
        "text_patterns": [r"squarespace"],
        "header_patterns": [r"x-powered-by.*squarespace", r"server.*squarespace"],
        "category": "CMS / Website builder",
    },
    "Weebly": {
        "url_patterns": [r"weebly\.com", r"weeblysite\.com"],
        "text_patterns": [r"weebly"],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
    "Google Sites": {
        "url_patterns": [r"sites\.google\.com"],
        "text_patterns": [r"sites\.google\.com"],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
    "Jimdo": {
        "url_patterns": [r"jimdo\.com", r"jimdofree\.com", r"jimdosite\.com"],
        "text_patterns": [r"jimdo"],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
    "Webflow": {
        "url_patterns": [r"webflow\.io", r"webflow\.com"],
        "text_patterns": [r"webflow"],
        "header_patterns": [r"x-powered-by.*webflow"],
        "category": "CMS / Website builder",
    },
    "Drupal": {
        "url_patterns": [],
        "text_patterns": [r'"generator":\s*"Drupal', r"Drupal\.settings"],
        "header_patterns": [r"x-generator.*drupal", r"x-drupal-"],
        "category": "CMS / Website builder",
    },
    "Joomla": {
        "url_patterns": [],
        "text_patterns": [r'"generator":\s*"Joomla'],
        "header_patterns": [],
        "category": "CMS / Website builder",
    },
}

# Compile all patterns once
_COMPILED = {
    name: {
        "url": [re.compile(p, re.I) for p in sig["url_patterns"]],
        "text": [re.compile(p, re.I) for p in sig["text_patterns"]],
        "header": [re.compile(p, re.I) for p in sig["header_patterns"]],
        "category": sig["category"],
    }
    for name, sig in PLATFORMS.items()
}


# -------------------------------------------------------------------
# Detection helpers
# -------------------------------------------------------------------

def _collect_urls_from_soup(soup):
    """Collect every href/src/action attribute from a parsed page."""
    urls = set()
    for tag in soup.find_all(True):
        for attr in ("href", "src", "action", "data-src", "data-url"):
            val = tag.get(attr, "")
            if val:
                urls.add(val)
    return urls


def _match_platform(name, sig, final_url, page_urls, page_text, headers_str):
    for rx in sig["url"]:
        if rx.search(final_url):
            return True
        for u in page_urls:
            if rx.search(u):
                return True
    for rx in sig["text"]:
        if rx.search(page_text):
            return True
    for rx in sig["header"]:
        if rx.search(headers_str):
            return True
    return False


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
    return _session


def detect(website_url):
    """
    Visit *website_url* and return a dict:
      {
        "software": str,         # platform name or "Unknown / Custom"
        "category": str,
        "final_url": str,        # after redirects
        "error": str or None,
      }
    """
    if not website_url or not website_url.strip():
        return {"software": "No Website", "category": "No Website", "final_url": "", "error": None}

    url = website_url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    time.sleep(REQUEST_DELAY)
    session = _get_session()

    try:
        resp = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        final_url = resp.url
        page_html = resp.text
        headers_str = " ".join(f"{k}: {v}" for k, v in resp.headers.items())
    except requests.exceptions.SSLError:
        # Retry without SSL verification for self-signed certs
        try:
            resp = session.get(
                url, headers=HEADERS, timeout=TIMEOUT,
                allow_redirects=True, verify=False
            )
            final_url = resp.url
            page_html = resp.text
            headers_str = " ".join(f"{k}: {v}" for k, v in resp.headers.items())
        except Exception as exc:
            return {"software": "Error", "category": "Error", "final_url": url, "error": str(exc)}
    except Exception as exc:
        return {"software": "Error", "category": "Error", "final_url": url, "error": str(exc)}

    soup = BeautifulSoup(page_html, "lxml")
    page_urls = _collect_urls_from_soup(soup)
    page_text = page_html  # match against full HTML for generator meta etc.

    # For SPAs the HTML shell is near-empty; fetch manifest.json if present
    # so platforms like Commit (which declare their name there) are detectable.
    manifest_tag = soup.find("link", rel="manifest")
    if manifest_tag and manifest_tag.get("href"):
        try:
            manifest_url = urljoin(final_url, manifest_tag["href"])
            manifest_resp = session.get(manifest_url, headers=HEADERS, timeout=TIMEOUT)
            page_text += " " + manifest_resp.text
        except Exception:
            pass

    # Check platform signatures in priority order (swim-specific first)
    for name, sig in _COMPILED.items():
        if _match_platform(name, sig, final_url, page_urls, page_text, headers_str):
            log.debug("  → %s detected for %s", name, url)
            return {
                "software": name,
                "category": sig["category"],
                "final_url": final_url,
                "error": None,
            }

    return {
        "software": "Unknown / Custom",
        "category": "Unknown / Custom",
        "final_url": final_url,
        "error": None,
    }
