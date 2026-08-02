from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path


def _spreadsheet_safe(value: object) -> object:
    if not isinstance(value, str):
        return value
    significant = value.lstrip(" \t\r\n")
    if significant.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def read_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    """Read a bounded CSV file and validate its schema."""
    if not path.is_file():
        raise FileNotFoundError(f"CSV file does not exist: {path}")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f"CSV file is unexpectedly large: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual_fields = set(reader.fieldnames or ())
        missing = required_fields - actual_fields
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        rows = list(reader)

    if len(rows) > 10_000:
        raise ValueError("CSV contains more than 10,000 rows")
    return rows


def write_csv_atomic(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    """Write a CSV through a temporary file so a failure cannot corrupt existing data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(
                {key: _spreadsheet_safe(value) for key, value in row.items()} for row in rows
            )
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
