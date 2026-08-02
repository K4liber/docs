from __future__ import annotations

from datetime import date

import pytest

from active_investing import cli
from active_investing.collector import CSV_FIELDS
from active_investing.io_utils import write_csv_atomic


def test_run_command_persists_data_and_creates_dated_ranking(tmp_path, monkeypatch) -> None:
    data_path = tmp_path / "companies.csv"
    config_path = tmp_path / "ranking.toml"
    config_path.write_text(
        """
[weights]
pe_ratio = 1
pb_ratio = 1
revenue_growth = 1
profit_margin = 1
products_score = 1
undervalued_score = 1
volatility_score = 1
[filters]
max_pe_ratio = 100
max_pb_ratio = 30
min_revenue_growth = 0
min_profit_margin = 0
min_products_score = 50
""".strip(),
        encoding="utf-8",
    )

    record = {
        "Source Rank": 1,
        "Ticker": "EXM",
        "Company Name": "Example",
        "Market Cap": 100,
        "P/E Ratio": 20,
        "P/B Ratio": 4,
        "Revenue Growth": 0.15,
        "Profit Margin": 0.20,
        "Products and services": "Example services",
        "Products and services score": 70,
        "Undervalued score": 60,
        "Volatility score": 40,
    }

    def fake_collect(output_path, **kwargs):
        write_csv_atomic(output_path, CSV_FIELDS, [record])
        return [record]

    monkeypatch.setattr(cli, "collect_to_csv", fake_collect)

    exit_code = cli.main(
        [
            "run",
            "--limit",
            "1",
            "--data-file",
            str(data_path),
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path),
            "--as-of",
            date(2026, 8, 2).isoformat(),
        ]
    )

    ranking_path = tmp_path / "rank_2026-08-02.csv"
    assert exit_code == 0
    assert data_path.is_file()
    assert ranking_path.read_text(encoding="utf-8").splitlines() == [
        "Company Name,Weighted Score",
        "Example,81.43",
    ]


def test_run_command_propagates_collection_failure(tmp_path, monkeypatch) -> None:
    rank_called = False

    def fail_collection(*args, **kwargs):
        raise ValueError("provider unavailable")

    def track_rank(*args, **kwargs):
        nonlocal rank_called
        rank_called = True

    monkeypatch.setattr(cli, "collect_to_csv", fail_collection)
    monkeypatch.setattr(cli, "rank_csv", track_rank)

    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "run",
                "--data-file",
                str(tmp_path / "companies.csv"),
                "--output-dir",
                str(tmp_path),
                "--as-of",
                "2026-08-02",
            ]
        )

    assert error.value.code == 1
    assert rank_called is False
    assert not (tmp_path / "rank_2026-08-02.csv").exists()


def test_packaged_default_config_matches_editable_config() -> None:
    editable_config = cli.PACKAGED_CONFIG_FILE.parents[2] / "ranking.toml"

    assert cli.PACKAGED_CONFIG_FILE.read_text(encoding="utf-8").splitlines() == (
        editable_config.read_text(encoding="utf-8").splitlines()
    )
