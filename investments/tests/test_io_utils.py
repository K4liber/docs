from __future__ import annotations

import pytest

from active_investing.io_utils import write_csv_atomic


@pytest.mark.parametrize("formula", ["=2+2", "+2", "-2", "@SUM(A1)", "  =2+2"])
def test_write_csv_escapes_spreadsheet_formulas(tmp_path, formula: str) -> None:
    path = tmp_path / "safe.csv"

    write_csv_atomic(path, ["Name"], [{"Name": formula}, {"Name": "Example"}])

    contents = path.read_text(encoding="utf-8")
    assert f"'{formula}" in contents
    assert "Example" in contents
