"""Tests for main.py — survey orchestration and release notes."""

from datetime import datetime, timezone

import pandas as pd
import pytest

import main


@pytest.mark.parametrize("github_actions", ["true", "false"])
def test_run_info_published_results_url(tmp_path, monkeypatch, github_actions):
    run_info = tmp_path / "RUN_INFO.md"
    monkeypatch.setattr(main, "RUN_INFO_MD", run_info)
    monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    df = pd.DataFrame([
        {"website": "https://example.com", "software": "WordPress", "error": None},
    ])

    main._write_run_info(df, datetime(2026, 10, 1, tzinfo=timezone.utc))

    text = run_info.read_text(encoding="utf-8")
    assert (
        "**Published results:** https://swimblocks.github.io/swim-club-tech-survey/"
        in text
    )
    assert "gavinbee" not in text
    assert "canada-swim-tech-survey" not in text
