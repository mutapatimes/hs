"""Tests for scoring.loader.

These build a tiny throwaway .xlsx so the tests never depend on the real
(PII, git-ignored) customer file.
"""
import pandas as pd
import pytest

from scoring.loader import load_data


@pytest.fixture
def tiny_xlsx(tmp_path):
    """Write a small workbook mimicking the real export's shape."""
    path = tmp_path / "tiny.xlsx"
    pd.DataFrame(
        {
            "Name": ["  Ada Lovelace ", "Alan Turing"],
            "Spent": [12000, 3400],
            "LATEST_BILLING_ZIP": ["SW3 6RS", None],
        }
    ).to_excel(path, sheet_name="Export", index=False)
    return path


def test_load_returns_dataframe(tiny_xlsx):
    df = load_data(tiny_xlsx)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["Name", "Spent", "LATEST_BILLING_ZIP"]


def test_text_is_stripped(tiny_xlsx):
    df = load_data(tiny_xlsx)
    assert df.loc[0, "Name"] == "Ada Lovelace"


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_data("does/not/exist.xlsx")
