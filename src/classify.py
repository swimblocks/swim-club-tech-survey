"""
Post-detection reclassification rules applied after software detection.

Splits "Unknown / Custom" into more meaningful buckets:
  - University / Institution  (university, CÉGEP, college club pages)
  - Quebec Custom Site        (QC clubs with bespoke French-language sites)
  - No Website                (invalid URLs such as Bing search pages)

Normalizes historical TeamUnify / GoMotion labels to SportsEngine Motion.
Ambiguous historical SportsEngine labels become Unknown / Custom.
"""

import re

import pandas as pd

_UNIV_URL = re.compile(
    r"ualberta\.ca|ucalgary\.ca|uquebec\.ca|uqtr\.|"
    r"cegep|cegepstfe|cegeprdl|"
    r"uottawa\.ca|utoronto\.ca|mcgill\.ca|ubc\.ca|sfu\.ca|uvic\.ca",
    re.I,
)

_UNIV_NAME = re.compile(
    r"universit|cegep|cégep|college|\brseq\b",
    re.I,
)

_INVALID_URL = re.compile(r"bing\.com/search|google\.com/search", re.I)

PLATFORM_ALIASES = {
    "TeamUnify": "SportsEngine Motion",
    "GoMotion": "SportsEngine Motion",
}


def normalize_platform_aliases(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize legacy products; discard ambiguous parent-brand classifications."""
    df = df.copy()
    ambiguous = df["software"] == "SportsEngine"
    df.loc[ambiguous, ["software", "category"]] = "Unknown / Custom"
    legacy = df["software"].isin(PLATFORM_ALIASES)
    df["software"] = df["software"].replace(PLATFORM_ALIASES)
    df.loc[legacy, "category"] = "Swim-specific"
    return df


def reclassify(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply in-place reclassifications to a results DataFrame.
    Returns the modified DataFrame.
    """
    df = normalize_platform_aliases(df)

    for i, row in df.iterrows():
        if row["software"] != "Unknown / Custom":
            continue

        website = str(row.get("website") or "")
        name = str(row.get("name") or "")
        province = str(row.get("province") or "").upper().strip()

        # Broken / search-engine URLs
        if _INVALID_URL.search(website):
            df.at[i, "software"] = "No Website"
            df.at[i, "category"] = "No Website"
            continue

        # University / CÉGEP / institutional club pages
        if _UNIV_URL.search(website) or _UNIV_NAME.search(name):
            df.at[i, "software"] = "University / Institution"
            df.at[i, "category"] = "University / Institution"
            continue

        # Quebec clubs with custom/unknown sites
        if province == "QC":
            df.at[i, "software"] = "Quebec Custom Site"
            df.at[i, "category"] = "Quebec Custom Site"
            continue

        # Also catch Quebec custom sites already promoted from a prior reclassification
        # pass (name-based university check for QC clubs)
        if row["software"] == "Quebec Custom Site" and _UNIV_NAME.search(name):
            df.at[i, "software"] = "University / Institution"
            df.at[i, "category"] = "University / Institution"

    return df
