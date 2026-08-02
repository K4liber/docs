from __future__ import annotations

import pytest

from active_investing.ranking import RankingConfig, rank_rows


def config(focus: str | None = None) -> RankingConfig:
    weights = {
        "pe_ratio": 0.15,
        "pb_ratio": 0.10,
        "revenue_growth": 0.20,
        "profit_margin": 0.20,
        "products_score": 0.20,
        "undervalued_score": 0.10,
        "volatility_score": 0.05,
    }
    if focus is not None:
        weights = {name: float(name == focus) for name in weights}
    return RankingConfig(
        weights=weights,
        max_pe_ratio=100,
        max_pb_ratio=30,
        min_revenue_growth=0,
        min_profit_margin=0,
        min_products_score=50,
    )


def row(name: str, ticker: str, **overrides: str) -> dict[str, str]:
    values = {
        "Company Name": name,
        "Ticker": ticker,
        "P/E Ratio": "20",
        "P/B Ratio": "4",
        "Revenue Growth": "0.15",
        "Profit Margin": "0.20",
        "Products and services score": "70",
        "Undervalued score": "60",
        "Volatility score": "40",
    }
    values.update(overrides)
    return values


def test_rank_rows_filters_and_orders_companies() -> None:
    rows = [
        row("Strong", "AAA", **{"Revenue Growth": "0.30", "Profit Margin": "0.35"}),
        row("Weak", "BBB", **{"Revenue Growth": "0.01", "Profit Margin": "0.01"}),
        row("Filtered", "CCC", **{"P/E Ratio": "-5"}),
    ]

    ranked = rank_rows(rows, config())

    assert [item["Company Name"] for item in ranked] == ["Strong", "Weak"]
    assert ranked[0]["Weighted Score"] > ranked[1]["Weighted Score"]


def test_rank_rows_excludes_missing_metrics() -> None:
    rows = [row("Incomplete", "AAA", **{"P/B Ratio": ""})]

    assert rank_rows(rows, config()) == []


def test_rank_rows_excludes_product_score_above_100() -> None:
    rows = [row("Invalid", "AAA", **{"Products and services score": "101"})]

    assert rank_rows(rows, config()) == []


@pytest.mark.parametrize(
    ("metric", "column", "preferred", "other"),
    [
        ("pe_ratio", "P/E Ratio", "10", "20"),
        ("pb_ratio", "P/B Ratio", "2", "4"),
        ("revenue_growth", "Revenue Growth", "0.30", "0.10"),
        ("profit_margin", "Profit Margin", "0.30", "0.10"),
        ("products_score", "Products and services score", "80", "60"),
        ("undervalued_score", "Undervalued score", "80", "60"),
        ("volatility_score", "Volatility score", "80", "60"),
    ],
)
def test_each_weighted_criterion_prefers_the_expected_company(
    metric: str,
    column: str,
    preferred: str,
    other: str,
) -> None:
    rows = [
        row("Preferred", "AAA", **{column: preferred}),
        row("Other", "BBB", **{column: other}),
    ]

    ranked = rank_rows(rows, config(focus=metric))

    assert [item["Company Name"] for item in ranked] == ["Preferred", "Other"]
