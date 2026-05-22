"""Tests for src/clubs.py — club discovery and address parsing."""

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from src.clubs import (
    _city_from_address,
    _make_club,
    _merge_provincial,
    _parse_nl_pdfs,
    _province_from_address,
    apply_suspects,
    fetch_all_clubs,
)


class TestProvinceFromAddress:
    def test_bc(self):
        assert _province_from_address("123 Main St V5K 0A1") == "BC"

    def test_ontario(self):
        assert _province_from_address("45 King St M5V 2T6") == "ON"

    def test_quebec(self):
        assert _province_from_address("12 Rue des Érables H2X 1Y4") == "QC"

    def test_alberta(self):
        assert _province_from_address("99 Jasper Ave T5J 1W2") == "AB"

    def test_nova_scotia(self):
        assert _province_from_address("1 Spring Garden Rd B3J 3R4") == "NS"

    def test_pei(self):
        assert _province_from_address("40 Enman Cres C1E 1E6") == "PE"

    def test_new_brunswick(self):
        assert _province_from_address("100 Brunswick St E3B 1G8") == "NB"

    def test_newfoundland(self):
        assert _province_from_address("10 Water St A1C 1A5") == "NL"

    def test_manitoba(self):
        assert _province_from_address("300 Main St R3C 1B8") == "MB"

    def test_saskatchewan(self):
        assert _province_from_address("2220 College Ave S4P 1C4") == "SK"

    def test_yukon(self):
        assert _province_from_address("100 Main St Y1A 2B5") == "YT"

    def test_northwest_territories(self):
        assert _province_from_address("5020 48 St X1A 2N6") == "NT"

    def test_no_postal_code(self):
        assert _province_from_address("123 Unknown Street") == ""

    def test_empty(self):
        assert _province_from_address("") == ""

    def test_lowercase_postal(self):
        assert _province_from_address("123 main st m5v 2t6") == "ON"


class TestCityFromAddress:
    def test_single_word_city(self):
        assert _city_from_address("Vancouver V5K 0A1") == "Vancouver"

    def test_multi_word_city(self):
        assert _city_from_address("St. John's A1C 1A5") == "St. John's"

    def test_with_street(self):
        assert _city_from_address("100 Main St Toronto M5V 2T6") == "100 Main St Toronto"

    def test_no_postal_code(self):
        assert _city_from_address("No postal code here") == ""

    def test_empty(self):
        assert _city_from_address("") == ""



@pytest.fixture(autouse=True)
def no_snapshot_writes(monkeypatch):
    """Prevent tests from overwriting data/clubs.json."""
    monkeypatch.setattr("src.clubs._save_snapshot", lambda clubs: None)


class TestFetchAllClubs:
    _SAMPLE_CLUBS = [
        {
            "name": "Test Swim Club",
            "address": "100 Main St M5V 2T6",
            "website": "https://testswimclub.ca",
            "phone": "",
            "lat": "43.6",
            "lng": "-79.4",
            "category": "",
            "type": "",
        },
        {
            "name": "Facebook Club",
            "address": "200 Oak Ave V5K 0A1",
            "website": "https://www.facebook.com/facebookclub",
            "phone": "",
            "lat": "49.2",
            "lng": "-123.1",
            "category": "",
            "type": "",
        },
        {
            "name": "No Website Club",
            "address": "300 Elm St H2X 1Y4",
            "website": "",
            "phone": "",
            "lat": "45.5",
            "lng": "-73.6",
            "category": "",
            "type": "",
        },
    ]

    def _make_response(self, clubs):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = "load_clubs(" + json.dumps(clubs) + ")"
        return mock

    @patch("src.clubs.requests.get")
    def test_basic_fetch(self, mock_get):
        mock_get.return_value = self._make_response(self._SAMPLE_CLUBS)
        clubs = fetch_all_clubs(force_refresh=True)
        assert len(clubs) == 3

    @patch("src.clubs.requests.get")
    def test_province_derived_from_postal(self, mock_get):
        mock_get.return_value = self._make_response(self._SAMPLE_CLUBS)
        clubs = fetch_all_clubs(force_refresh=True)
        by_name = {c["name"]: c for c in clubs}
        assert by_name["Test Swim Club"]["province"] == "ON"
        assert by_name["Facebook Club"]["province"] == "BC"
        assert by_name["No Website Club"]["province"] == "QC"

    @patch("src.clubs.requests.get")
    def test_facebook_url_cleared(self, mock_get):
        mock_get.return_value = self._make_response(self._SAMPLE_CLUBS)
        clubs = fetch_all_clubs(force_refresh=True)
        by_name = {c["name"]: c for c in clubs}
        assert by_name["Facebook Club"]["website"] == ""

    @patch("src.clubs.requests.get")
    def test_deduplication(self, mock_get):
        duplicate = self._SAMPLE_CLUBS + [self._SAMPLE_CLUBS[0]]
        mock_get.return_value = self._make_response(duplicate)
        clubs = fetch_all_clubs(force_refresh=True)
        names = [c["name"] for c in clubs]
        assert names.count("Test Swim Club") == 1

    @patch("src.clubs.requests.get")
    def test_jsonp_without_wrapper(self, mock_get):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = json.dumps(self._SAMPLE_CLUBS[:1])
        mock_get.return_value = mock
        clubs = fetch_all_clubs(force_refresh=True)
        assert len(clubs) == 1

    @patch("src.clubs.SNAPSHOT_PATH")
    @patch("src.clubs.requests.get")
    def test_network_error_no_snapshot_returns_empty(self, mock_get, mock_path):
        import requests as req
        mock_get.side_effect = req.RequestException("timeout")
        mock_path.exists.return_value = False
        clubs = fetch_all_clubs(force_refresh=True)
        assert clubs == []


class TestExclusions:
    """Excluded entries must be absent from both the returned list and the saved snapshot."""

    _CSCA = {
        "name": "CSCA",
        "address": "100 Main St V5K 0A1",
        "website": "https://www.csca.org",
        "phone": "", "lat": "", "lng": "", "category": "", "type": "",
    }
    _OFFICIALS = {
        "name": "Officials Registration ON",
        "address": "200 King St M5V 2T6",
        "website": "",
        "phone": "", "lat": "", "lng": "", "category": "", "type": "",
    }
    _REAL_CLUB = {
        "name": "Real Swim Club",
        "address": "300 Elm St T5J 1W2",
        "website": "https://realswimclub.ca",
        "phone": "", "lat": "", "lng": "", "category": "", "type": "",
    }

    def _make_response(self, clubs):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = "load_clubs(" + json.dumps(clubs) + ")"
        return mock

    @patch("src.clubs.requests.get")
    def test_excluded_website_not_returned(self, mock_get):
        mock_get.return_value = self._make_response([self._CSCA, self._REAL_CLUB])
        clubs = fetch_all_clubs(force_refresh=True)
        assert not any(c["website"] == "https://www.csca.org" for c in clubs)
        assert any(c["name"] == "Real Swim Club" for c in clubs)

    @patch("src.clubs.requests.get")
    def test_excluded_name_not_returned(self, mock_get):
        mock_get.return_value = self._make_response([self._OFFICIALS, self._REAL_CLUB])
        clubs = fetch_all_clubs(force_refresh=True)
        assert not any(c["name"] == "Officials Registration ON" for c in clubs)
        assert any(c["name"] == "Real Swim Club" for c in clubs)

    @patch("src.clubs.requests.get")
    def test_excluded_not_saved_to_snapshot(self, mock_get, monkeypatch):
        """Regression guard: _filter_clubs must run before _save_snapshot."""
        saved = []
        monkeypatch.setattr("src.clubs._save_snapshot", lambda clubs: saved.extend(clubs))
        mock_get.return_value = self._make_response([self._CSCA, self._OFFICIALS, self._REAL_CLUB])
        fetch_all_clubs(force_refresh=True)
        assert not any(c["website"] == "https://www.csca.org" for c in saved)
        assert not any(c["name"] == "Officials Registration ON" for c in saved)


class TestParseNlPdfs:
    """Unit tests for _parse_nl_pdfs — Swimming NL directory scraper."""

    # GoDaddy CDN URLs are protocol-relative (//img1.wsimg.com/…)
    _DIRECTORY_HTML = """
    <html><body>
      <a href="//img1.wsimg.com/aqua-aces.pdf">Aqua Aces Swim Club 2025-26(pdf)Download</a>
      <a href="//img1.wsimg.com/exec.pdf">Swimming NL Executive 2025-26(pdf)Download</a>
      <a href="//img1.wsimg.com/vikings.pdf">Vikings Aquatic Club(pdf)Download</a>
    </body></html>
    """

    def _make_directory_response(self):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        mock.text = self._DIRECTORY_HTML
        return mock

    def _make_pdf_response(self, website="N/A"):
        mock = MagicMock()
        mock.raise_for_status = MagicMock()
        pdf_text = f"Club Name Aqua Aces Swim Club\nClub Website {website}\nClub email address test@test.com\n"
        mock.content = pdf_text.encode()
        return mock

    def _call_parse(self, pdf_website="N/A"):
        r = self._make_directory_response()
        pdf_text = f"Club Name Aqua Aces Swim Club\nClub Website {pdf_website}\nClub email address test@test.com\n"
        with patch("src.clubs.requests.get") as mock_get, \
             patch("pdfplumber.open") as mock_pdf_open:
            mock_get.return_value = self._make_pdf_response(pdf_website)
            mock_page = MagicMock()
            mock_page.extract_text.return_value = pdf_text
            mock_pdf_open.return_value.__enter__.return_value.pages = [mock_page]
            return _parse_nl_pdfs("NL", r, source_url="https://swimmingnl.ca/directory")

    def test_club_names_parsed(self):
        clubs = self._call_parse()
        names = [c["name"] for c in clubs]
        assert "Aqua Aces Swim Club" in names
        assert "Vikings Aquatic Club" in names

    def test_executive_excluded(self):
        clubs = self._call_parse()
        assert not any("executive" in c["name"].lower() for c in clubs)

    def test_website_na_cleared(self):
        clubs = self._call_parse(pdf_website="N/A")
        aqua = next(c for c in clubs if c["name"] == "Aqua Aces Swim Club")
        assert aqua["website"] == ""

    def test_website_blank_line_not_bled_into_next_field(self):
        """Regression: blank Club Website field must not capture the next line."""
        r = self._make_directory_response()
        # "Club Website" on its own line, next line is email field
        pdf_text = "Club Name Test Club\nClub Website\nClub email address info@test.com\n"
        with patch("src.clubs.requests.get") as mock_get, \
             patch("pdfplumber.open") as mock_pdf_open:
            mock_get.return_value = self._make_pdf_response()
            mock_page = MagicMock()
            mock_page.extract_text.return_value = pdf_text
            mock_pdf_open.return_value.__enter__.return_value.pages = [mock_page]
            clubs = _parse_nl_pdfs("NL", r, source_url="https://swimmingnl.ca/directory")
        assert all(c["website"] == "" for c in clubs)

    def test_protocol_relative_pdf_url_resolved(self):
        """Regression: //img1.wsimg.com/… hrefs must have https: prepended."""
        captured_urls = []
        r = self._make_directory_response()
        pdf_text = "Club Name Aqua Aces Swim Club\nClub Website https://aquaaces.ca\n"
        with patch("src.clubs.requests.get") as mock_get, \
             patch("pdfplumber.open") as mock_pdf_open:
            mock_get.return_value = self._make_pdf_response("https://aquaaces.ca")
            mock_get.side_effect = lambda url, **kw: (captured_urls.append(url), self._make_pdf_response("https://aquaaces.ca"))[1]
            mock_page = MagicMock()
            mock_page.extract_text.return_value = pdf_text
            mock_pdf_open.return_value.__enter__.return_value.pages = [mock_page]
            _parse_nl_pdfs("NL", r, source_url="https://swimmingnl.ca/directory")
        assert all(url.startswith("https://") for url in captured_urls)

    def test_website_extracted_when_present(self):
        clubs = self._call_parse(pdf_website="https://aquaaces.ca")
        aqua = next(c for c in clubs if c["name"] == "Aqua Aces Swim Club")
        assert aqua["website"] == "https://aquaaces.ca"

    def test_province_set(self):
        clubs = self._call_parse()
        for c in clubs:
            assert c["province"] == "NL"

    def test_source_url_set(self):
        clubs = self._call_parse()
        for c in clubs:
            assert c["source_url"] == "https://swimmingnl.ca/directory"


class TestSuspectsOut:
    """_make_club with suspects_out captures unresolved suspects as full records."""

    def test_unresolved_suspect_saved_to_suspects_out(self, tmp_path, monkeypatch):
        res_file = tmp_path / "name_resolutions.json"
        res_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("src.name_resolution.NAME_RESOLUTIONS_PATH", res_file)

        suspects_out = []
        result = _make_club("Aqua Aces Swim Clun", "https://aquaaces.ca", "NL",
                             suspects_out=suspects_out)
        assert result is None
        assert len(suspects_out) == 1
        assert suspects_out[0]["name"] == "Aqua Aces Swim Clun"
        assert suspects_out[0]["website"] == "https://aquaaces.ca"
        assert suspects_out[0]["province"] == "NL"

    def test_saved_skip_not_added_to_suspects_out(self, tmp_path, monkeypatch):
        resolutions = {"Aqua Aces Swim Clun": {"action": "skip"}}
        res_file = tmp_path / "name_resolutions.json"
        res_file.write_text(json.dumps(resolutions), encoding="utf-8")
        monkeypatch.setattr("src.name_resolution.NAME_RESOLUTIONS_PATH", res_file)

        suspects_out = []
        result = _make_club("Aqua Aces Swim Clun", "https://aquaaces.ca", "NL",
                             suspects_out=suspects_out)
        assert result is None
        assert suspects_out == []  # saved skip resolution, not an unresolved suspect

    def test_suspects_out_none_still_skips(self, tmp_path, monkeypatch):
        res_file = tmp_path / "name_resolutions.json"
        res_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("src.name_resolution.NAME_RESOLUTIONS_PATH", res_file)

        # suspects_out=None — club is still skipped, record just isn't captured
        result = _make_club("Aqua Aces Swim Clun", "https://aquaaces.ca", "NL",
                             suspects_out=None)
        assert result is None


class TestApplySuspects:
    """apply_suspects merges resolved clubs from clubs_suspects.json into clubs.json."""

    _EXISTING = [{"name": "Existing Club", "province": "ON",
                  "province_name": "Ontario", "website": "https://existing.ca",
                  "source_url": "https://findaclub.swimming.ca/"}]
    _SUSPECT = {"name": "Aqua Aces Swim Clun", "province": "NL",
                "province_name": "Newfoundland and Labrador",
                "website": "https://aquaaces.ca", "source_url": "https://swimmingnl.ca/directory"}

    def _setup(self, tmp_path, monkeypatch, suspects, resolutions, existing=None):
        suspects_file = tmp_path / "clubs_suspects.json"
        suspects_file.write_text(json.dumps(suspects), encoding="utf-8")
        monkeypatch.setattr("src.clubs.SUSPECTS_PATH", suspects_file)

        res_file = tmp_path / "name_resolutions.json"
        res_file.write_text(json.dumps(resolutions), encoding="utf-8")
        monkeypatch.setattr("src.name_resolution.NAME_RESOLUTIONS_PATH", res_file)

        snapshot_file = tmp_path / "clubs.json"
        snapshot_file.write_text(json.dumps(existing or self._EXISTING), encoding="utf-8")
        monkeypatch.setattr("src.clubs.SNAPSHOT_PATH", snapshot_file)

        # Override the autouse no_snapshot_writes fixture so apply_suspects can save
        monkeypatch.setattr("src.clubs._save_snapshot", lambda clubs: snapshot_file.write_text(
            json.dumps([{"name": c["name"], "province": c["province"],
                         "province_name": c["province_name"], "website": c["website"],
                         "source_url": c.get("source_url", "")} for c in clubs],
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        ))
        return snapshot_file

    def test_rename_adds_corrected_club(self, tmp_path, monkeypatch):
        resolutions = {"Aqua Aces Swim Clun": {"action": "rename", "to": "Aqua Aces Swim Club"}}
        snapshot_file = self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions)

        added = apply_suspects()

        assert added == 1
        saved = json.loads(snapshot_file.read_text())
        names = [c["name"] for c in saved]
        assert "Aqua Aces Swim Club" in names
        assert "Aqua Aces Swim Clun" not in names

    def test_keep_adds_original_name(self, tmp_path, monkeypatch):
        resolutions = {"Aqua Aces Swim Clun": {"action": "keep"}}
        snapshot_file = self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions)

        added = apply_suspects()

        assert added == 1
        saved = json.loads(snapshot_file.read_text())
        assert any(c["name"] == "Aqua Aces Swim Clun" for c in saved)

    def test_skip_discards_club(self, tmp_path, monkeypatch):
        resolutions = {"Aqua Aces Swim Clun": {"action": "skip"}}
        snapshot_file = self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions)

        added = apply_suspects()

        assert added == 0
        saved = json.loads(snapshot_file.read_text())
        assert not any("Aqua Aces" in c["name"] for c in saved)

    def test_no_suspects_file_returns_zero(self, tmp_path, monkeypatch):
        suspects_file = tmp_path / "clubs_suspects.json"
        monkeypatch.setattr("src.clubs.SUSPECTS_PATH", suspects_file)
        assert apply_suspects() == 0

    def test_suspects_file_deleted_after_apply(self, tmp_path, monkeypatch):
        resolutions = {"Aqua Aces Swim Clun": {"action": "skip"}}
        snapshot_file = self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions)
        suspects_file = tmp_path / "clubs_suspects.json"

        apply_suspects()

        assert not suspects_file.exists()

    def test_deduplication_by_name(self, tmp_path, monkeypatch):
        existing_with_club = self._EXISTING + [
            {"name": "Aqua Aces Swim Club", "province": "NL",
             "province_name": "Newfoundland and Labrador",
             "website": "", "source_url": ""}
        ]
        resolutions = {"Aqua Aces Swim Clun": {"action": "rename", "to": "Aqua Aces Swim Club"}}
        self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions, existing=existing_with_club)

        added = apply_suspects()
        assert added == 0  # already present under the resolved name

    def test_unresolved_suspect_skipped_with_warning(self, tmp_path, monkeypatch, caplog):
        snapshot_file = self._setup(tmp_path, monkeypatch, [self._SUSPECT], resolutions={})

        import logging
        with caplog.at_level(logging.WARNING, logger="src.clubs"):
            added = apply_suspects()

        assert added == 0
        assert any("No resolution saved" in r.message for r in caplog.records)


class TestMergeProvincial:
    def test_name_match_backfills_missing_website_and_source(self, monkeypatch):
        clubs = [{
            "name": "Westlock Gators",
            "province": "AB",
            "province_name": "Alberta",
            "website": "",
            "source_url": "https://findaclub.swimming.ca/",
        }]
        provincial = [{
            "name": "Westlock Gators",
            "province": "AB",
            "province_name": "Alberta",
            "website": "https://www.gomotionapp.com/team/assawgsc/page/home",
            "source_url": "https://swimalberta.ca/community/clubs/find-a-club/",
        }]

        monkeypatch.setattr("src.clubs._PROVINCIAL_SOURCES", [("AB", "html_divs_ab", "https://example.com")])
        monkeypatch.setattr("src.clubs._fetch_provincial", lambda *args, **kwargs: provincial)

        merged = _merge_provincial(clubs, unresolved=[])

        assert merged == clubs
        assert len(merged) == 1
        assert merged[0]["website"] == "https://www.gomotionapp.com/team/assawgsc/page/home"
        assert merged[0]["source_url"] == "https://swimalberta.ca/community/clubs/find-a-club/"

    def test_name_match_does_not_overwrite_existing_website(self, monkeypatch):
        clubs = [{
            "name": "Westlock Gators",
            "province": "AB",
            "province_name": "Alberta",
            "website": "https://westlockgators.ca",
            "source_url": "https://findaclub.swimming.ca/",
        }]
        provincial = [{
            "name": "Westlock Gators",
            "province": "AB",
            "province_name": "Alberta",
            "website": "https://www.gomotionapp.com/team/assawgsc/page/home",
            "source_url": "https://swimalberta.ca/community/clubs/find-a-club/",
        }]

        monkeypatch.setattr("src.clubs._PROVINCIAL_SOURCES", [("AB", "html_divs_ab", "https://example.com")])
        monkeypatch.setattr("src.clubs._fetch_provincial", lambda *args, **kwargs: provincial)

        merged = _merge_provincial(clubs, unresolved=[])

        assert len(merged) == 1
        assert merged[0]["website"] == "https://westlockgators.ca"
        assert merged[0]["source_url"] == "https://findaclub.swimming.ca/"
