"""FileSource — read customers from a local spreadsheet (the offline/demo source).

Lets the whole pipeline (sync → store → API → fulfilment view) run end-to-end with no
Shopify credentials, using the same `.xlsx` exports the batch engine already loads via
`scoring.loader.load_data`. Each customer is emitted as one synthetic order so the
fulfilment surface has a pick list to show.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd

from config import DATA_FILE, DATA_SHEET
from halia.ports import CustomerSource
from scoring.loader import load_data


class FileSource(CustomerSource):
    name = "file"

    def __init__(self, path: str | Path = DATA_FILE, sheet: str = DATA_SHEET, limit: int | None = None):
        self.path = Path(path)
        self.sheet = sheet
        self.limit = limit
        self._df: pd.DataFrame | None = None

    def _frame(self) -> pd.DataFrame:
        if self._df is None:
            df = load_data(self.path, self.sheet)
            if "CUST_ID" not in df.columns:
                df = df.copy()
                df["CUST_ID"] = [f"{self.name}-{i}" for i in range(len(df))]
            self._df = df if self.limit is None else df.head(self.limit)
        return self._df

    def fetch_all(self) -> Iterator[dict]:
        for _, row in self._frame().iterrows():
            yield row.to_dict()

    def iter_orders(self) -> Iterator[dict]:
        for _, row in self._frame().iterrows():
            yield {
                "order_id": f"O-{row['CUST_ID']}",
                "customer_id": str(row["CUST_ID"]),
                "email": row.get("EMAIL_ADDR"),
                "created_at": str(row.get("Last Shopped") or ""),
            }
