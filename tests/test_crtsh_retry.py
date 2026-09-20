"""Tests for crt.sh retry/backoff (no real network; requests is mocked)."""

from unittest.mock import MagicMock, patch

import brandguard.discovery.crtsh_source as cs


def _resp(status=200, text="[]", json_data=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=json_data if json_data is not None else [])
    return r


def test_retries_through_rate_limit_then_succeeds():
    calls = {"n": 0}

    def flaky(url, timeout, headers):
        calls["n"] += 1
        if calls["n"] < 3:
            return _resp(429, "rate limited")
        return _resp(200, "[{}]", [{"name_value": "paypal-login.com"}])

    with patch("requests.get", side_effect=flaky), patch("time.sleep"):
        out = cs.search_crtsh("paypal", retries=3, base_delay=0.01)
    assert calls["n"] == 3 and len(out) == 1


def test_empty_body_retried_then_soft_empty():
    calls = {"n": 0}

    def empty(url, timeout, headers):
        calls["n"] += 1
        return _resp(200, text="")

    with patch("requests.get", side_effect=empty), patch("time.sleep"):
        out = cs.search_crtsh("x", retries=2, base_delay=0.01)
    assert out == [] and calls["n"] == 3  # 1 + 2 retries


def test_success_does_not_retry():
    calls = {"n": 0}

    def ok(url, timeout, headers):
        calls["n"] += 1
        return _resp(200, "[{}]", [{"name_value": "paypal-x.com"}])

    with patch("requests.get", side_effect=ok), patch("time.sleep"):
        out = cs.search_crtsh("paypal", retries=3, base_delay=0.01)
    assert calls["n"] == 1 and len(out) == 1


def test_real_error_status_not_retried():
    calls = {"n": 0}

    def err(url, timeout, headers):
        calls["n"] += 1
        return _resp(503, text="err")

    with patch("requests.get", side_effect=err), patch("time.sleep"):
        out = cs.search_crtsh("x", retries=3, base_delay=0.01)
    assert out == [] and calls["n"] == 1
