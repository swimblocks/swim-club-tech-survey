"""Tests for src/detector.py — platform detection logic."""

from unittest.mock import MagicMock, patch

import pytest

from src.detector import _collect_urls_from_soup, detect
from bs4 import BeautifulSoup


def _mock_response(url="https://example.com", html="", headers=None, status=200):
    mock = MagicMock()
    mock.url = url
    mock.text = html
    mock.status_code = status
    mock.headers = headers or {}
    return mock


def _page(body_html, final_url="https://example.com"):
    return _mock_response(url=final_url, html=f"<html><body>{body_html}</body></html>")


class TestNoWebsite:
    def test_empty_string(self):
        result = detect("")
        assert result["software"] == "No Website"

    def test_none_like_blank(self):
        result = detect("   ")
        assert result["software"] == "No Website"


class TestRedirectDetection:
    @patch("src.detector._get_session")
    def test_gomotion_final_url(self, mock_sess):
        mock_sess.return_value.get.return_value = _mock_response(
            url="https://www.gomotionapp.com/team/onaa/page/home"
        )
        result = detect("https://myclub.ca")
        assert result["software"] == "SportsEngine Motion"

    @patch("src.detector._get_session")
    def test_poolq_final_url(self, mock_sess):
        mock_sess.return_value.get.return_value = _mock_response(
            url="https://myclub.poolq.net/"
        )
        result = detect("https://myclub.poolq.net")
        assert result["software"] == "PoolQ"

    @patch("src.detector._get_session")
    def test_teamunify_final_url(self, mock_sess):
        mock_sess.return_value.get.return_value = _mock_response(
            url="https://www.teamunify.com/team/canta/page/home"
        )
        result = detect("https://oldclub.ca")
        assert result["software"] == "SportsEngine Motion"


class TestScriptSrcDetection:
    @patch("src.detector._get_session")
    def test_gomotion_script_src(self, mock_sess):
        html = '<script src="https://www.gomotionapp.com/js/main.js"></script>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "SportsEngine Motion"

    @patch("src.detector._get_session")
    def test_jerseywatch_script_src(self, mock_sess):
        html = '<script src="https://webapp-assets.jerseywatch.com/v1/embed.js"></script>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "JerseyWatch"

    @patch("src.detector._get_session")
    def test_teamlinkt_script_src(self, mock_sess):
        html = '<script src="https://cdn-league-prod-static.teamlinkt.com/app.js"></script>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "TeamLinkt"

    @patch("src.detector._get_session")
    def test_sidearm_sports_script(self, mock_sess):
        html = '<link href="https://fonts.sidearmsports.com/css/fonts.css" rel="stylesheet">'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "Sidearm Sports"

    @patch("src.detector._get_session")
    def test_wix_static_src(self, mock_sess):
        html = '<script src="https://static.wixstatic.com/js/site.js"></script>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "Wix"

    @patch("src.detector._get_session")
    def test_wordpress_wp_content(self, mock_sess):
        html = '<link rel="stylesheet" href="/wp-content/themes/swim/style.css">'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "WordPress"


class TestManifestDetection:
    @patch("src.detector._get_session")
    def test_commit_via_manifest(self, mock_sess):
        main_html = (
            '<html><head>'
            '<link rel="manifest" href="/manifest.json">'
            '</head><body><div id="root"></div></body></html>'
        )
        manifest_json = '{"short_name":"Commit","name":"Commit Swimming"}'
        session = mock_sess.return_value
        session.get.side_effect = [
            _mock_response(url="https://scarswimming.ca/", html=main_html),
            _mock_response(url="https://scarswimming.ca/manifest.json", html=manifest_json),
        ]
        assert detect("https://scarswimming.ca")["software"] == "Commit"


class TestTextPatternDetection:
    @patch("src.detector._get_session")
    def test_gomotion_text(self, mock_sess):
        html = '<a href="/login">Powered by gomotionapp</a>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "SportsEngine Motion"

    @patch("src.detector._get_session")
    def test_jonas_powered_by(self, mock_sess):
        html = "<footer>Powered by Jonas Club Software</footer>"
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "Jonas Club Software"

    @patch("src.detector._get_session")
    def test_godaddy_generator_meta(self, mock_sess):
        html = (
            '<meta name="generator" content="Starfield Technologies; '
            'Go Daddy Website Builder 8.0.0000">'
        )
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "GoDaddy Website Builder"

    @patch("src.detector._get_session")
    def test_squarespace_text(self, mock_sess):
        html = '<script src="https://static1.squarespace.com/static/js/main.js"></script>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "Squarespace"

    @patch("src.detector._get_session")
    def test_amilia_link(self, mock_sess):
        html = '<a href="https://app.amilia.com/store/en/myclub/shop">Register</a>'
        mock_sess.return_value.get.return_value = _page(html)
        assert detect("https://example.com")["software"] == "Amilia"


class TestSportsEngineProducts:
    @pytest.mark.parametrize("domain", [
        "www.gomotionapp.com", "motion.sportsengine.com", "www.teamunify.com",
    ])
    @patch("src.detector._get_session")
    def test_tenant_url_with_parent_branding(self, mock_sess, domain):
        mock_sess.return_value.get.return_value = _page(
            '<footer><a href="https://www.sportsengine.com">Powered by SportsEngine</a></footer>',
            final_url=f"https://{domain}/team/example/page/home",
        )
        result = detect("https://example.com")
        assert result["software"] == "SportsEngine Motion"
        assert result["category"] == "Swim-specific"

    @pytest.mark.parametrize("domain", [
        "www.gomotionapp.com", "motion.sportsengine.com", "www.teamunify.com",
    ])
    @patch("src.detector._get_session")
    def test_assets_with_parent_branding(self, mock_sess, domain):
        mock_sess.return_value.get.return_value = _page(
            f'<script src="https://{domain}/js/main.js"></script>'
            '<footer>Powered by SportsEngine</footer>'
        )
        assert detect("https://example.com")["software"] == "SportsEngine Motion"

    @pytest.mark.parametrize("brand", [
        "SportsEngine Motion", "sportsengine motion", "TeamUnify", "Team Unify", "GoMotion",
    ])
    @patch("src.detector._get_session")
    def test_current_and_legacy_branding(self, mock_sess, brand):
        mock_sess.return_value.get.return_value = _page(f"Powered by {brand}")
        assert detect("https://example.com")["software"] == "SportsEngine Motion"

    @pytest.mark.parametrize("url", [
        "https://club.sportngin.com/",
        "https://www.sportsenginehq.com/",
        "https://www.sportsengine.com/hq",
    ])
    @patch("src.detector._get_session")
    def test_hq_url(self, mock_sess, url):
        mock_sess.return_value.get.return_value = _page(
            "Powered by SportsEngine", final_url=url,
        )
        result = detect("https://example.com")
        assert result["software"] == "SportsEngine HQ"
        assert result["category"] == "Sports management"

    @patch("src.detector._get_session")
    def test_hq_assets(self, mock_sess):
        mock_sess.return_value.get.return_value = _page(
            '<script src="https://cdn1.sportngin.com/app.js"></script>'
        )
        assert detect("https://example.com")["software"] == "SportsEngine HQ"

    @patch("src.detector._get_session")
    def test_hq_branding(self, mock_sess):
        mock_sess.return_value.get.return_value = _page("Powered by SportsEngine HQ")
        assert detect("https://example.com")["software"] == "SportsEngine HQ"

    @patch("src.detector._get_session")
    def test_parent_branding_does_not_identify_product(self, mock_sess):
        mock_sess.return_value.get.return_value = _page(
            '<a href="https://www.sportsengine.com">Powered by SportsEngine</a>'
        )
        assert detect("https://example.com")["software"] == "Unknown / Custom"


class TestHeaderDetection:
    @patch("src.detector._get_session")
    def test_wix_header(self, mock_sess):
        mock_sess.return_value.get.return_value = _mock_response(
            headers={"x-wix-request-id": "abc123"}
        )
        assert detect("https://example.com")["software"] == "Wix"


class TestUnknown:
    @patch("src.detector._get_session")
    def test_no_signals(self, mock_sess):
        mock_sess.return_value.get.return_value = _page(
            "<h1>Welcome to Our Swim Club</h1><p>Custom built site.</p>"
        )
        assert detect("https://example.com")["software"] == "Unknown / Custom"


class TestErrors:
    @patch("src.detector._get_session")
    def test_connection_error(self, mock_sess):
        import requests as req
        mock_sess.return_value.get.side_effect = req.exceptions.ConnectionError("refused")
        result = detect("https://example.com")
        assert result["software"] == "Error"
        assert result["error"] is not None

    @patch("src.detector._get_session")
    def test_ssl_retry_fallback(self, mock_sess):
        import requests as req
        session = mock_sess.return_value
        # First call raises SSL error, second succeeds
        session.get.side_effect = [
            req.exceptions.SSLError("cert mismatch"),
            _page('<script src="https://static.wixstatic.com/js/x.js"></script>'),
        ]
        result = detect("https://example.com")
        assert result["software"] == "Wix"


class TestCollectUrlsFromSoup:
    def test_collects_script_src(self):
        soup = BeautifulSoup('<script src="https://cdn.example.com/app.js"></script>', "lxml")
        urls = _collect_urls_from_soup(soup)
        assert "https://cdn.example.com/app.js" in urls

    def test_collects_link_href(self):
        soup = BeautifulSoup('<link href="https://fonts.example.com/font.css">', "lxml")
        urls = _collect_urls_from_soup(soup)
        assert "https://fonts.example.com/font.css" in urls

    def test_collects_form_action(self):
        soup = BeautifulSoup('<form action="https://register.example.com/submit"></form>', "lxml")
        urls = _collect_urls_from_soup(soup)
        assert "https://register.example.com/submit" in urls

    def test_collects_anchor_href(self):
        soup = BeautifulSoup('<a href="https://app.amilia.com/store/myclub">Register</a>', "lxml")
        urls = _collect_urls_from_soup(soup)
        assert "https://app.amilia.com/store/myclub" in urls

    def test_ignores_missing_attrs(self):
        soup = BeautifulSoup("<div><p>No links here</p></div>", "lxml")
        urls = _collect_urls_from_soup(soup)
        assert len(urls) == 0
