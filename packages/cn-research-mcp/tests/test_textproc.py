from __future__ import annotations

from datetime import date, datetime, time, timezone

import pandas as pd
import pytest

from cn_research_mcp import textproc


def test_clean_plain_text():
    assert textproc.clean_text("  贵州茅台\n发布公告  ") == ("贵州茅台 发布公告", False)


def test_clean_removes_html_tags():
    assert textproc.clean_text("<p>买入</p><b>评级</b>") == ("买入评级", False)


def test_clean_removes_nested_tags():
    assert textproc.clean_text("<scr<script>ipt>alert(1)</script>") == ("ipt>alert(1)", False)


def test_clean_decodes_entities():
    assert textproc.clean_text("A&amp;B&nbsp;C") == ("A&B C", False)


def test_clean_removes_control_characters():
    assert textproc.clean_text("a\x00b\x07c\x1fd") == ("abcd", False)


def test_clean_collapses_whitespace():
    assert textproc.clean_text("a\t\tb\u3000\u3000c\r\nd") == ("a b c d", False)


def test_clean_empty_is_none():
    assert textproc.clean_text("   ") == (None, False)
    assert textproc.clean_text("<b></b>") == (None, False)


@pytest.mark.parametrize("value", [None, float("nan"), pd.NaT, "nan", "None", ""])
def test_clean_missing_is_none(value):
    assert textproc.clean_text(value) == (None, False)


def test_clean_truncates_with_ellipsis_within_limit():
    text, truncated = textproc.clean_text("字" * 500, 300)
    assert truncated is True and text.endswith("…") and len(text) == 300


def test_clean_exact_limit_not_truncated():
    text, truncated = textproc.clean_text("字" * 300, 300)
    assert truncated is False and text == "字" * 300


def test_clean_limit_one():
    assert textproc.clean_text("ab", 1) == ("…", True)


def test_clean_strips_leading_zero_width():
    assert textproc.clean_text("a\u200bb\ufeffc") == ("abc", False)


def test_link_allows_eastmoney_and_subdomains():
    assert textproc.clean_link("http://finance.eastmoney.com/a/1.html")
    assert textproc.clean_link("https://eastmoney.com/x")


def test_link_allows_other_whitelisted_hosts():
    assert textproc.clean_link("https://www.cls.cn/telegraph")
    assert textproc.clean_link("https://irm.cninfo.com.cn/x")
    assert textproc.clean_link("https://news.10jqka.com.cn/x")


def test_link_rejects_lookalike_host():
    assert textproc.clean_link("https://eastmoney.com.evil.example/x") is None
    assert textproc.clean_link("https://evileastmoney.com/x") is None


def test_link_rejects_non_http_scheme():
    assert textproc.clean_link("javascript:alert(1)") is None
    assert textproc.clean_link("ftp://eastmoney.com/x") is None


def test_link_rejects_relative_and_malformed():
    assert textproc.clean_link("/a/1.html") is None
    assert textproc.clean_link("http://[bad") is None
    assert textproc.clean_link(None) is None


def test_link_ignores_userinfo_host():
    assert textproc.clean_link("https://eastmoney.com@evil.example/x") is None


def test_parse_time_naive_gets_cn_offset():
    assert textproc.parse_time("2026-11-16 09:30:00") == "2026-11-16T09:30:00+08:00"


def test_parse_time_utc_converted():
    assert textproc.parse_time("2026-11-16T01:30:00Z") == "2026-11-16T09:30:00+08:00"
    assert textproc.parse_time("2026-11-16T01:30:00+00:00") == "2026-11-16T09:30:00+08:00"


def test_parse_time_accepts_date_and_slash_format():
    assert textproc.parse_time("2026-11-16") == "2026-11-16T00:00:00+08:00"
    assert textproc.parse_time("2026/11/16 09:30") == "2026-11-16T09:30:00+08:00"


def test_parse_time_accepts_python_objects():
    assert textproc.parse_time(date(2026, 11, 16)) == "2026-11-16T00:00:00+08:00"
    moment = datetime(2026, 11, 16, 1, 30, tzinfo=timezone.utc)
    assert textproc.parse_time(moment) == "2026-11-16T09:30:00+08:00"


@pytest.mark.parametrize("value", ["not-a-time", "2026-13-40 99:99", "202611ab", None, float("nan")])
def test_parse_time_invalid_is_none(value):
    assert textproc.parse_time(value) is None


def test_parse_date():
    assert textproc.parse_date("2026-11-16 09:30:00") == "2026-11-16"
    assert textproc.parse_date("bad") is None


def test_combine_date_time_objects():
    assert textproc.combine_date_time(date(2026, 11, 16), time(9, 30)) == "2026-11-16T09:30:00+08:00"


def test_combine_date_time_string_time():
    assert textproc.combine_date_time("2026-11-16", "09:30:26") == "2026-11-16T09:30:26+08:00"


def test_combine_missing_time_is_midnight():
    assert textproc.combine_date_time("2026-11-16", None) == "2026-11-16T00:00:00+08:00"


def test_combine_invalid_time_is_none():
    assert textproc.combine_date_time("2026-11-16", "25:99") is None


def test_raw_value_keeps_upstream_text_and_number():
    assert textproc.raw_value("3.2%") == "3.2%"
    assert textproc.raw_value("1.5万亿") == "1.5万亿"
    assert textproc.raw_value(3.2) == 3.2
    assert textproc.raw_value(3.0) == 3
    assert textproc.raw_value(float("nan")) is None


def test_to_number():
    assert textproc.to_number("3") == 3.0
    assert textproc.to_number(2.5) == 2.5
    assert textproc.to_number("★★") is None
    assert textproc.to_number(True) is None
    assert textproc.to_number(float("inf")) is None
