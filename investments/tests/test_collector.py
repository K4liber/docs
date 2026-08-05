from __future__ import annotations

import json
import math
import statistics
from contextlib import nullcontext

import pytest

from active_investing import collector
from active_investing.collector import (
    CSV_FIELDS,
    ENERGY_SOURCE_URL,
    TECH_SOURCE_URL,
    CompanySeed,
    calculate_price_scores,
    collect_records,
    collect_to_csv,
    fetch_top_companies,
    load_manual_values,
    parse_quote_summary,
    parse_top_companies,
)


def test_parse_top_companies_reads_validated_table_rows() -> None:
    html = """
    <table><tbody>
      <tr>
        <td></td><td class="rank-td" data-sort="1">1</td>
        <td><div class="company-name">Example Corp</div><div class="company-code">EXM</div></td>
        <td data-sort="123456789">$123 M</td>
      </tr>
    </tbody></table>
    """

    companies = parse_top_companies(html, sector="tech", limit=1)

    assert companies[0].source_rank == 1
    assert companies[0].sector == "tech"
    assert companies[0].ticker == "EXM"
    assert companies[0].name == "Example Corp"
    assert companies[0].market_cap == 123_456_789


def test_parse_top_companies_rejects_incomplete_source() -> None:
    with pytest.raises(ValueError, match="Expected 1 valid companies"):
        parse_top_companies("<html></html>", sector="tech", limit=1)


def test_fetch_top_companies_combines_tech_and_energy(monkeypatch) -> None:
    requested_urls: list[str] = []

    monkeypatch.setattr(collector, "_build_session", lambda: nullcontext(object()))

    def fake_get(session, url, accept):
        requested_urls.append(url)
        return type("Payload", (), {"text": "<html></html>"})()

    def fake_parse(html, sector, limit):
        return [CompanySeed(1, sector, f"{sector[:1].upper()}EX", f"{sector} co", 100)]

    monkeypatch.setattr(collector, "_get", fake_get)
    monkeypatch.setattr(collector, "parse_top_companies", fake_parse)

    companies = fetch_top_companies(limit=1)

    assert requested_urls == [TECH_SOURCE_URL, ENERGY_SOURCE_URL]
    assert [company.sector for company in companies] == ["tech", "energy"]


def test_parse_quote_summary_reads_embedded_response_body() -> None:
    summary = {"summaryDetail": {"trailingPE": {"raw": 20.5}}}
    body = json.dumps({"quoteSummary": {"result": [summary]}})
    envelope = json.dumps({"status": 200, "body": body})
    html = (
        '<script type="application/json" data-sveltekit-fetched '
        f'data-url="https://query1.finance.yahoo.com/v10/finance/quoteSummary/EXM">'
        f"{envelope}</script>"
    )

    assert parse_quote_summary(html) == summary


def test_price_scores_are_bounded() -> None:
    closes = [100 + index % 8 - index * 0.05 for index in range(80)]

    scores = calculate_price_scores(closes)

    assert 0 <= scores["undervalued_score"] <= 100
    assert 0 <= scores["volatility_score"] <= 100
    assert scores["annualized_volatility"] >= 0


def test_price_score_thresholds_are_exact() -> None:
    flat_scores = calculate_price_scores([100.0] * 40)
    drawdown_scores = calculate_price_scores([100.0] * 39 + [70.0])

    assert flat_scores["undervalued_score"] == 0
    assert flat_scores["volatility_score"] == 0
    assert drawdown_scores["undervalued_score"] == 100


def test_price_scores_calculate_intermediate_components() -> None:
    prices = [100.0] * 30 + [70.0] * 9 + [85.0]
    alternating_returns = [0.02 if index % 2 else -0.02 for index in range(39)]
    volatile_prices = [100.0]
    for daily_return in alternating_returns:
        volatile_prices.append(volatile_prices[-1] * (1 + daily_return))

    price_scores = calculate_price_scores(prices)
    volatility_scores = calculate_price_scores(volatile_prices)
    expected_volatility = statistics.stdev(alternating_returns) * math.sqrt(252)
    expected_score = 100 * (expected_volatility - 0.15) / 0.45

    assert price_scores["undervalued_score"] == pytest.approx(50.0)
    assert volatility_scores["annualized_volatility"] == pytest.approx(expected_volatility)
    assert volatility_scores["volatility_score"] == pytest.approx(expected_score)


def test_collect_records_preserves_intentionally_blank_description(monkeypatch) -> None:
    seed = CompanySeed(1, "tech", "EXM", "Example", 100)
    monkeypatch.setattr(
        collector,
        "_fetch_financial_data",
        lambda unused_seed: {"Products and services": "provider description"},
    )

    records = collect_records(
        [seed],
        {"EXM": {"Products and services": "", "Products and services score": "75"}},
        workers=1,
    )

    assert records[0]["Products and services"] == ""
    assert records[0]["Products and services score"] == "75"


def test_load_manual_values_rejects_out_of_range_score(tmp_path) -> None:
    path = tmp_path / "companies.csv"
    path.write_text(
        "Ticker,Products and services,Products and services score\nEXM,Example,101\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be between 0 and 100"):
        load_manual_values(path)


def test_load_manual_values_normalizes_signed_score(tmp_path) -> None:
    path = tmp_path / "companies.csv"
    path.write_text(
        "Ticker,Products and services,Products and services score\nEXM,Example,+50\n",
        encoding="utf-8",
    )

    values = load_manual_values(path)

    assert values["EXM"]["Products and services score"] == "50"


def test_incomplete_provider_data_does_not_replace_existing_csv(tmp_path, monkeypatch) -> None:
    path = tmp_path / "companies.csv"
    original = ",".join(CSV_FIELDS) + "\n1,tech,OLD,Old Company,100,,,,,Keep,50,,,,,,\n"
    path.write_text(original, encoding="utf-8")
    seed = CompanySeed(1, "tech", "EXM", "Example", 100)
    monkeypatch.setattr(collector, "fetch_top_companies", lambda limit: [seed])
    monkeypatch.setattr(
        collector,
        "collect_records",
        lambda *args, **kwargs: [{"Ticker": "EXM", "Company Name": "Example"}],
    )

    with pytest.raises(ValueError, match="Fewer than half"):
        collect_to_csv(path, limit=1)

    assert path.read_text(encoding="utf-8") == original
