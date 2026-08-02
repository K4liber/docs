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
REQUIRED_COLUMNS = {"Company Name", "Ticker", *METRIC_COLUMNS.values()}
RANK_FIELDS = ["Company Name", "Weighted Score"]


@dataclass(frozen=True)
class RankingConfig:
    weights: dict[str, float]
    max_pe_ratio: float
    max_pb_ratio: float
    min_revenue_growth: float
    min_profit_margin: float
    min_products_score: float


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

    return RankingConfig(
        weights=normalized_weights,
        max_pe_ratio=float(filters["max_pe_ratio"]),
        max_pb_ratio=float(filters["max_pb_ratio"]),
        min_revenue_growth=float(filters["min_revenue_growth"]),
        min_profit_margin=float(filters["min_profit_margin"]),
        min_products_score=float(filters["min_products_score"]),
    )


def _eligible(metrics: dict[str, float | None], config: RankingConfig) -> bool:
    if any(value is None for value in metrics.values()):
        return False
    values = {name: float(value) for name, value in metrics.items()}
    return (
        0 < values["pe_ratio"] <= config.max_pe_ratio
        and 0 < values["pb_ratio"] <= config.max_pb_ratio
        and values["revenue_growth"] >= config.min_revenue_growth
        and values["profit_margin"] >= config.min_profit_margin
        and config.min_products_score <= values["products_score"] <= 100
        and 0 <= values["undervalued_score"] <= 100
        and 0 <= values["volatility_score"] <= 100
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
    candidates: list[tuple[dict[str, str], dict[str, float]]] = []
    seen_tickers: set[str] = set()
    for row in rows:
        ticker = row["Ticker"].strip().upper()
        if not ticker or ticker in seen_tickers:
            raise ValueError(f"CSV contains an empty or duplicate ticker: {ticker or '<empty>'}")
        seen_tickers.add(ticker)
        metrics = {name: _finite_float(row[column]) for name, column in METRIC_COLUMNS.items()}
        if _eligible(metrics, config):
            candidates.append((row, {name: float(value) for name, value in metrics.items()}))

    if not candidates:
        return []

    distributions = {
        name: sorted(metrics[name] for _, metrics in candidates)
        for name in ("pe_ratio", "pb_ratio", "revenue_growth", "profit_margin")
    }
    weight_total = sum(config.weights.values())
    ranked: list[dict[str, object]] = []
    for row, metrics in candidates:
        normalized = {
            name: _percentile(metrics[name], distributions[name], name in LOWER_IS_BETTER)
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
        ranked.append(
            {
                "Company Name": row["Company Name"].strip(),
                "Weighted Score": round(weighted_score, 2),
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
