"""Tests for src/classify.py — post-detection reclassification rules."""

import pandas as pd
import pytest

from src.classify import reclassify


def _df(rows):
    """Build a minimal DataFrame from a list of (name, province, website, software) tuples."""
    return pd.DataFrame(
        [
            {
                "name": name,
                "province": province,
                "website": website,
                "software": software,
                "category": software,
            }
            for name, province, website, software in rows
        ]
    )


class TestInvalidUrls:
    def test_bing_search_becomes_no_website(self):
        df = _df([("Brock Niagara Aquatics", "ON",
                   "https://www.bing.com/search?q=brock+niagara", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "No Website"

    def test_google_search_becomes_no_website(self):
        df = _df([("Some Club", "BC",
                   "https://www.google.com/search?q=some+club", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "No Website"


class TestUniversityByUrl:
    def test_ualberta(self):
        df = _df([("U of A Masters", "AB",
                   "https://www.ualberta.ca/swim", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_uqtr(self):
        df = _df([("UQTR Swim", "QC",
                   "https://oraprdnt.uqtr.uquebec.ca/portail/gscw031", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_cegep(self):
        df = _df([("Cégep Sainte-Foy Swim", "QC",
                   "https://cegepstfe.ca/sports", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_mcgill(self):
        df = _df([("McGill Swim", "QC",
                   "https://www.mcgill.ca/athletics/swim", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"


class TestUniversityByName:
    def test_universite_in_name(self):
        df = _df([("Club de natation Université Laval", "QC",
                   "https://rougeetornatation.com", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_rseq_in_name(self):
        df = _df([("RSEQ - Cégep de Rivière-du-Loup", "QC",
                   "https://www.cegeprdl.ca/sports", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_college_in_name(self):
        df = _df([("Algonquin College Swim Club", "ON",
                   "https://customsite.ca", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"


class TestQuebecCustom:
    def test_qc_unknown_becomes_quebec_custom(self):
        df = _df([("Les Loutres", "QC",
                   "https://www.lesloutres.com", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "Quebec Custom Site"

    def test_non_qc_stays_unknown(self):
        df = _df([("Some Ontario Club", "ON",
                   "https://customsite.ca", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "Unknown / Custom"

    def test_nb_french_name_stays_unknown(self):
        # French name but NB province — should not be Quebec Custom
        df = _df([("Les Espadons", "NB",
                   "https://www.lesespadons.com", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "Unknown / Custom"


class TestPriorityOrder:
    def test_university_beats_quebec_custom(self):
        # QC province + university URL → University wins, not Quebec Custom
        df = _df([("UQTR Swim", "QC",
                   "https://uqtr.uquebec.ca/swim", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "University / Institution"

    def test_invalid_url_beats_university_name(self):
        # Bing search URL + university-sounding name → No Website wins
        df = _df([("University Swim", "ON",
                   "https://www.bing.com/search?q=university+swim", "Unknown / Custom")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "No Website"


class TestNonUnknownRowsUntouched:
    @pytest.mark.parametrize("software", ["SportsEngine Motion", "SportsEngine HQ"])
    def test_sportsengine_unchanged(self, software):
        df = _df([("Example Club", "ON", "https://example.com", software)])
        out = reclassify(df)
        assert out.iloc[0]["software"] == software

    def test_wordpress_unchanged(self):
        df = _df([("WP Club", "QC", "https://wpclub.ca", "WordPress")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "WordPress"

    def test_original_df_not_mutated(self):
        df = _df([("Les Loutres", "QC",
                   "https://www.lesloutres.com", "Unknown / Custom")])
        reclassify(df)
        assert df.iloc[0]["software"] == "Unknown / Custom"


class TestHistoricalPlatformAliases:
    def test_generic_brand_is_not_a_product(self):
        df = _df([("Example Club", "ON", "https://example.com", "SportsEngine")])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "Unknown / Custom"
        assert out.iloc[0]["category"] == "Unknown / Custom"
        assert df.iloc[0]["software"] == "SportsEngine"
        pd.testing.assert_frame_equal(reclassify(out), out)

    @pytest.mark.parametrize("alias", ["TeamUnify", "GoMotion"])
    def test_legacy_platform_normalized(self, alias):
        df = _df([("Example Club", "QC", "https://example.com", alias)])
        out = reclassify(df)
        assert out.iloc[0]["software"] == "SportsEngine Motion"
        assert out.iloc[0]["category"] == "Swim-specific"
        assert df.iloc[0]["software"] == alias
        pd.testing.assert_frame_equal(reclassify(out), out)
