"""Tests for adjudicator provider selection and .env handling."""

import os
from pathlib import Path

import pytest

from brandguard.triage.adjudicator import (
    AnthropicAdjudicator,
    OpenAIAdjudicator,
    RuleAdjudicator,
    _load_dotenv_once,
    get_adjudicator,
)


@pytest.fixture()
def clean_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_no_keys_selects_rule_adjudicator(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    assert isinstance(get_adjudicator(), RuleAdjudicator)


def test_anthropic_key_wins(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert isinstance(get_adjudicator(), AnthropicAdjudicator)


def test_openai_key_selected_when_only_openai(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert isinstance(get_adjudicator(), OpenAIAdjudicator)


def test_dotenv_fills_gap_but_does_not_override(clean_env, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text(
        "OPENAI_API_KEY=from-file\nANTHROPIC_API_KEY=also-from-file\n", encoding="utf-8"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    _load_dotenv_once()
    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"  # real env wins
    assert os.environ["OPENAI_API_KEY"] == "from-file"      # gap filled
