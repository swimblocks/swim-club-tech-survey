"""Tests for src/visualize.py — report generation."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from src.visualize import (
    PLATFORM_URLS,
    _EXCLUDE_FROM_DISTRIBUTION,
    _overall_chart_html,
    generate_html,
)


def _sample_df():
    return pd.DataFrame([
        {"name": "Club A", "province": "ON", "province_name": "Ontario",
         "software": "SportsEngine Motion", "category": "Swim-specific", "members": None, "website": "https://a.com"},
        {"name": "Club B", "province": "ON", "province_name": "Ontario",
         "software": "SportsEngine Motion", "category": "Swim-specific", "members": None, "website": "https://b.com"},
        {"name": "Club C", "province": "BC", "province_name": "British Columbia",
         "software": "WordPress", "category": "CMS / Website builder", "members": None, "website": "https://c.com"},
        {"name": "Club D", "province": "QC", "province_name": "Quebec",
         "software": "No Website", "category": "No Website", "members": None, "website": ""},
        {"name": "Club E", "province": "AB", "province_name": "Alberta",
         "software": "Error", "category": "Error", "members": None, "website": "https://e.com"},
        {"name": "Club F", "province": "BC", "province_name": "British Columbia",
         "software": "PoolQ", "category": "Swim-specific", "members": None, "website": "https://f.poolq.net"},
    ])


class TestExcludeFromDistribution:
    def test_error_excluded(self):
        assert "Error" in _EXCLUDE_FROM_DISTRIBUTION

    def test_no_website_excluded(self):
        assert "No Website" in _EXCLUDE_FROM_DISTRIBUTION


class TestOverallChartHtml:
    def test_excludes_error(self):
        html = _overall_chart_html(_sample_df())
        # Error should not appear as a bar label
        assert 'Error' not in html or 'hbar-row' not in html.split('Error')[0].split('\n')[-1]

    def test_excludes_no_website(self):
        html = _overall_chart_html(_sample_df())
        assert ">No Website<" not in html

    def test_includes_sportsengine_motion(self):
        html = _overall_chart_html(_sample_df())
        assert "SportsEngine Motion" in html

    def test_sportsengine_motion_is_link(self):
        html = _overall_chart_html(_sample_df())
        assert f'href="{PLATFORM_URLS["SportsEngine Motion"]}"' in html

    def test_poolq_is_link(self):
        html = _overall_chart_html(_sample_df())
        assert f'href="{PLATFORM_URLS["PoolQ"]}"' in html

    def test_unknown_custom_has_no_link(self):
        df = _sample_df().copy()
        df.loc[len(df)] = {
            "name": "Mystery Club", "province": "SK", "province_name": "Saskatchewan",
            "software": "Unknown / Custom", "category": "Unknown / Custom",
            "members": None, "website": "https://mystery.ca",
        }
        html = _overall_chart_html(df)
        assert 'sw-nolink' in html

    def test_bar_count_shown(self):
        html = _overall_chart_html(_sample_df())
        # SportsEngine Motion has 2 clubs
        assert ">2<" in html

    def test_empty_df_returns_no_data(self):
        df = pd.DataFrame(columns=["software"])
        html = _overall_chart_html(df)
        assert "No data" in html


class TestPlatformUrls:
    def test_all_urls_start_with_https(self):
        for name, url in PLATFORM_URLS.items():
            assert url.startswith("https://"), f"{name} URL should start with https://"

    def test_major_platforms_present(self):
        for platform in ["SportsEngine Motion", "SportsEngine HQ", "PoolQ", "WordPress", "Wix", "Amilia"]:
            assert platform in PLATFORM_URLS, f"{platform} missing from PLATFORM_URLS"

    def test_generic_brand_is_not_a_product(self):
        assert "SportsEngine" not in PLATFORM_URLS


class TestGenerateHtml:
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            assert out.exists()
            assert out.stat().st_size > 5_000

    def test_valid_html_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            html = out.read_text(encoding="utf-8")
            assert "<!DOCTYPE html>" in html
            assert "<title>" in html
            assert "</html>" in html

    def test_stat_cards_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            html = out.read_text(encoding="utf-8")
            assert "Clubs surveyed" in html
            assert "Distinct platforms" in html

    def test_top_platform_excludes_no_website(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            html = out.read_text(encoding="utf-8")
            # SportsEngine Motion (2 clubs) should win, not No Website (1 club, excluded)
            assert "SportsEngine Motion" in html

    def test_historical_aliases_combined_in_report(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        df = _sample_df().iloc[:5].copy()
        df["software"] = [
            "TeamUnify", "GoMotion", "SportsEngine Motion", "SportsEngine HQ", "SportsEngine",
        ]
        df["category"] = ["Swim-specific"] * 3 + ["Sports management"] * 2
        original = df.copy()
        out = tmp_path / "report.html"
        generate_html(df, out)
        html = out.read_text(encoding="utf-8")
        assert "TeamUnify" not in html
        assert "GoMotion" not in html
        assert ">SportsEngine<" not in html
        assert ">Unknown / Custom<" in html
        assert ">3<" in html
        for platform in ["SportsEngine Motion", "SportsEngine HQ"]:
            assert f'href="{PLATFORM_URLS[platform]}"' in html
        pd.testing.assert_frame_equal(df, original)

    def test_data_table_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            html = out.read_text(encoding="utf-8")
            assert "clubTable" in html
            assert "Club A" in html

    def test_chart_js_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            generate_html(_sample_df(), out)
            html = out.read_text(encoding="utf-8")
            assert "chart.js" in html.lower()
