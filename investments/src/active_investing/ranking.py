from __future__ import annotations

import bisect
import math
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .io_utils import read_csv, write_csv_atomic

METRIC_COLUMNS = {
    "pe_ratio": "P/E Ratio",
    "pb_ratio": "P/B Ratio",
    "revenue_growth": "Revenue Growth",
    "profit_margin": "Profit Margin",
    "products_score": "Products and services score",
    "undervalued_score": "Undervalued score",
    "volatility_score": "Volatility score",
}
LOWER_IS_BETTER = {"pe_ratio", "pb_ratio"}
REQUIRED_COLUMNS = {"Company Name", "Ticker", "Sector", *METRIC_COLUMNS.values()}
RANK_FIELDS = [
    "Ticker",
    "Company Name",
    "Sector",
    "Weighted Score",
    "Valuation Score",
    "Fundamentals Score",
    "Undervalued Score",
    "Volatility Score",
    "Rebound From Low",
]


@dataclass(frozen=True)
class RankingConfig:
    weights: dict[str, float]
    max_pe_ratio: float
    max_pb_ratio: float
    min_revenue_growth: float
    min_profit_margin: float
    min_products_score: float
    min_rebound_from_low: float


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_config(path: Path) -> RankingConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    raw_weights = raw.get("weights")
    raw_filters = raw.get("filters")
    if not isinstance(raw_weights, dict) or not isinstance(raw_filters, dict):
        raise ValueError("ranking config must contain [weights] and [filters] tables")
    if set(raw_weights) != set(METRIC_COLUMNS):
        raise ValueError("ranking weights must define exactly: " + ", ".join(METRIC_COLUMNS))

    weights = {name: _finite_float(value) for name, value in raw_weights.items()}
    if any(value is None or value < 0 for value in weights.values()):
        raise ValueError("ranking weights must be finite, non-negative numbers")
    normalized_weights = {name: float(value) for name, value in weights.items()}
    if sum(normalized_weights.values()) <= 0:
        raise ValueError("at least one ranking weight must be positive")

    expected_filters = {
        "max_pe_ratio",
        "max_pb_ratio",
        "min_revenue_growth",
        "min_profit_margin",
        "min_products_score",
        "min_rebound_from_low",
    }
    if set(raw_filters) != expected_filters:
        raise ValueError(
            "ranking filters must define exactly: " + ", ".join(sorted(expected_filters))
        )
    filters = {name: _finite_float(value) for name, value in raw_filters.items()}
    if any(value is None for value in filters.values()):
        raise ValueError("ranking filters must be finite numbers")
    if float(filters["max_pe_ratio"]) <= 0 or float(filters["max_pb_ratio"]) <= 0:
        raise ValueError("maximum P/E and P/B filters must be positive")
    if not 0 <= float(filters["min_products_score"]) <= 100:
        raise ValueError("min_products_score must be between 0 and 100")
    if float(filters["min_rebound_from_low"]) < 0:
        raise ValueError("min_rebound_from_low must be a non-negative fraction")

    return RankingConfig(
        weights=normalized_weights,
        max_pe_ratio=float(filters["max_pe_ratio"]),
        max_pb_ratio=float(filters["max_pb_ratio"]),
        min_revenue_growth=float(filters["min_revenue_growth"]),
        min_profit_margin=float(filters["min_profit_margin"]),
        min_products_score=float(filters["min_products_score"]),
        min_rebound_from_low=float(filters["min_rebound_from_low"]),
    )


def _eligible(
    metrics: dict[str, float | None],
    current_price: float | None,
    year_low: float | None,
    config: RankingConfig,
) -> bool:
    if any(value is None for value in metrics.values()) or current_price is None or year_low is None:
        return False
    values = {name: float(value) for name, value in metrics.items()}
    if current_price <= 0 or year_low <= 0:
        return False
    rebound_from_low = (current_price - year_low) / year_low
    return (
        0 < values["pe_ratio"] <= config.max_pe_ratio
        and 0 < values["pb_ratio"] <= config.max_pb_ratio
        and values["revenue_growth"] >= config.min_revenue_growth
        and values["profit_margin"] >= config.min_profit_margin
        and config.min_products_score <= values["products_score"] <= 100
        and 0 <= values["undervalued_score"] <= 100
        and 0 <= values["volatility_score"] <= 100
        and rebound_from_low >= config.min_rebound_from_low
    )


def _percentile(value: float, sorted_values: list[float], lower_is_better: bool) -> float:
    if len(sorted_values) == 1:
        return 100.0
    left = bisect.bisect_left(sorted_values, value)
    right = bisect.bisect_right(sorted_values, value)
    rank = ((left + right - 1) / 2) / (len(sorted_values) - 1)
    return 100 * (1 - rank if lower_is_better else rank)


def rank_rows(rows: list[dict[str, str]], config: RankingConfig) -> list[dict[str, object]]:
    """Filter rows and calculate a weighted score on a common 0-100 scale."""
    candidates: list[tuple[dict[str, str], dict[str, float], str, float]] = []
    seen_tickers: set[str] = set()
    for row in rows:
        ticker = row["Ticker"].strip().upper()
        if not ticker or ticker in seen_tickers:
            raise ValueError(f"CSV contains an empty or duplicate ticker: {ticker or '<empty>'}")
        seen_tickers.add(ticker)
        sector = row.get("Sector", "").strip().lower()
        if not sector:
            continue
        metrics = {name: _finite_float(row[column]) for name, column in METRIC_COLUMNS.items()}
        current_price = _finite_float(row.get("Current Price"))
        year_low = _finite_float(row.get("52-Week Low"))
        if _eligible(metrics, current_price, year_low, config):
            candidates.append(
                (
                    row,
                    {name: float(value) for name, value in metrics.items()},
                    sector,
                    float((float(current_price) - float(year_low)) / float(year_low)),
                )
            )

    if not candidates:
        return []

    distributions: dict[str, dict[str, list[float]]] = {
        name: {} for name in ("pe_ratio", "pb_ratio", "revenue_growth", "profit_margin")
    }
    for metric_name in distributions:
        sectors = sorted({sector for _, _, sector, _ in candidates})
        for sector in sectors:
            distributions[metric_name][sector] = sorted(
                metrics[metric_name]
                for _, metrics, candidate_sector, _ in candidates
                if candidate_sector == sector
            )

    def _component_score(values: list[tuple[float, float]]) -> float:
        total_weight = sum(weight for _, weight in values)
        if total_weight <= 0:
            return sum(score for score, _ in values) / len(values)
        return sum(score * weight for score, weight in values) / total_weight

    weight_total = sum(config.weights.values())
    ranked: list[dict[str, object]] = []
    for row, metrics, sector, rebound_from_low in candidates:
        normalized = {
            name: _percentile(
                metrics[name],
                distributions[name][sector],
                name in LOWER_IS_BETTER,
            )
            for name in distributions
        }
        normalized.update(
            {
                name: metrics[name]
                for name in ("products_score", "undervalued_score", "volatility_score")
            }
        )
        weighted_score = (
            sum(normalized[name] * config.weights[name] for name in METRIC_COLUMNS) / weight_total
        )
        valuation_score = _component_score(
            [
                (normalized["pe_ratio"], config.weights["pe_ratio"]),
                (normalized["pb_ratio"], config.weights["pb_ratio"]),
            ]
        )
        fundamentals_score = _component_score(
            [
                (normalized["revenue_growth"], config.weights["revenue_growth"]),
                (normalized["profit_margin"], config.weights["profit_margin"]),
                (normalized["products_score"], config.weights["products_score"]),
            ]
        )
        ranked.append(
            {
                "Ticker": row["Ticker"].strip().upper(),
                "Company Name": row["Company Name"].strip(),
                "Sector": sector,
                "Weighted Score": round(weighted_score, 2),
                "Valuation Score": round(valuation_score, 2),
                "Fundamentals Score": round(fundamentals_score, 2),
                "Undervalued Score": round(normalized["undervalued_score"], 2),
                "Volatility Score": round(normalized["volatility_score"], 2),
                "Rebound From Low": round(rebound_from_low, 4),
            }
        )

    return sorted(ranked, key=lambda row: (-float(row["Weighted Score"]), str(row["Company Name"])))


def rank_csv(input_path: Path, output_dir: Path, config_path: Path, as_of: date) -> Path:
    rows = read_csv(input_path, REQUIRED_COLUMNS)
    config = load_config(config_path)
    ranked = rank_rows(rows, config)
    output_path = output_dir / f"rank_{as_of.isoformat()}.csv"
    write_csv_atomic(output_path, RANK_FIELDS, ranked)
    return output_path
