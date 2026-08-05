from __future__ import annotations

import argparse
import logging
from datetime import date
from importlib.resources import files
from pathlib import Path
from typing import NoReturn

from .collector import collect_to_csv
from .ranking import rank_csv

WORKING_DIRECTORY = Path.cwd()
DEFAULT_DATA_FILE = WORKING_DIRECTORY / "data" / "companies.csv"
LOCAL_CONFIG_FILE = WORKING_DIRECTORY / "ranking.toml"
PACKAGED_CONFIG_FILE = Path(str(files("active_investing").joinpath("default_ranking.toml")))
DEFAULT_CONFIG_FILE = LOCAL_CONFIG_FILE if LOCAL_CONFIG_FILE.is_file() else PACKAGED_CONFIG_FILE
DEFAULT_OUTPUT_DIR = WORKING_DIRECTORY / "data"


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a date in YYYY-MM-DD format") from error


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("expected an integer") from error
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"expected a value from {minimum} to {maximum}")
        return number

    return parse


def _score(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a number") from error
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("expected a score from 0 to 100")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="active-investing",
        description="Collect and rank top public technology and energy companies by market cap.",
    )
    parser.add_argument("--verbose", action="store_true", help="show detailed progress messages")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_collection_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
        command.add_argument(
            "--limit",
            type=_bounded_int(1, 100),
            default=100,
            help="number of companies to fetch per sector (tech and energy)",
        )
        command.add_argument("--workers", type=_bounded_int(1, 16), default=4)
        command.add_argument("--default-products-score", type=_score, default=50.0)

    collect = subparsers.add_parser("collect", help="refresh the source company CSV")
    add_collection_arguments(collect)

    rank = subparsers.add_parser("rank", help="rank an existing company CSV")
    rank.add_argument("--data-file", type=Path, default=DEFAULT_DATA_FILE)
    rank.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE)
    rank.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    rank.add_argument("--as-of", type=_date, default=date.today())

    run = subparsers.add_parser("run", help="collect current data and immediately rank it")
    add_collection_arguments(run)
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG_FILE)
    run.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    run.add_argument("--as-of", type=_date, default=date.today())
    return parser


def _fail(parser: argparse.ArgumentParser, error: Exception) -> NoReturn:
    parser.exit(1, f"error: {error}\n")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        if args.command in {"collect", "run"}:
            records = collect_to_csv(
                args.data_file,
                limit=args.limit,
                default_products_score=args.default_products_score,
                workers=args.workers,
            )
            print(f"Collected {len(records)} companies into {args.data_file}")
        if args.command in {"rank", "run"}:
            output_path = rank_csv(args.data_file, args.output_dir, args.config, args.as_of)
            print(f"Created ranking at {output_path}")
    except (OSError, ValueError) as error:
        _fail(parser, error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
