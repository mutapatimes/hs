"""Load the retailer's customer export into a pandas DataFrame.

This module only reads and lightly cleans the file. It deliberately does no
scoring — that lives elsewhere — so it stays easy to test and reuse.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

# openpyxl warns when a workbook carries no default style; harmless for reading.
warnings.filterwarnings(
    "ignore", message="Workbook contains no default style", module="openpyxl"
)

from config import DATA_FILE, DATA_SHEET


def load_data(
    path: Path | str = DATA_FILE,
    sheet: str = DATA_SHEET,
) -> pd.DataFrame:
    """Load the customer export and return a tidy DataFrame.

    Args:
        path: Path to the .xlsx export. Defaults to the configured data file.
        sheet: Worksheet name to read. Defaults to the configured sheet.

    Returns:
        A DataFrame with one row per customer.

    Raises:
        FileNotFoundError: If the data file is missing (with a helpful hint).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Data file not found: {path}\n"
            "Place the customer export at this path (it is git-ignored and "
            "stays local). See sample_data/README.md."
        )

    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")

    # Light, non-destructive cleanup:
    # - normalise column names (strip stray whitespace),
    # - strip whitespace from text cells ONLY (an object column can hold ints, e.g.
    #   a numeric CUST_ID alongside string ids; .str.strip() would turn those to NaN),
    # - drop fully-empty rows.
    df.columns = [str(c).strip() for c in df.columns]
    df = df.apply(
        lambda col: col.map(lambda x: x.strip() if isinstance(x, str) else x)
        if col.dtype == "object" else col
    )
    df = df.dropna(how="all").reset_index(drop=True)

    return df


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    frame = load_data()
    print(f"Loaded {len(frame):,} rows x {frame.shape[1]} columns")
