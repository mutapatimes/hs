"""Export the scored customers to a spreadsheet — the VIC-audit deliverable.

Produces a multi-sheet .xlsx:
  - "Hidden VICs"    : signal fired AND spend below the VIC threshold, ranked by
                       score then spend
  - "Above threshold": signal fired but already spending above the threshold
                       (validation — the method also catches clients you already rate)
  - "Signal summary": how many customers each signal flagged
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import EXPORT_FILE
from scoring.combine import (
    COUNT_COL,
    HIDDEN_COL,
    REASONS_COL,
    SCORE_COL,
    SIGNAL_WEIGHTS,
    active_signals,
    score_customers,
)

# Columns to show in the VIC sheets, in order (only those present are used).
_EXPORT_COLUMNS = [
    SCORE_COL, COUNT_COL, REASONS_COL,
    "Name", "Spent", "Items", "SEGMENT", "RFM SEGMENT", "RECENCY_BAND",
    "Last Shopped", "EMAIL_ADDR", "PHONE", "SA", "CUST_ID", "COMPANY_NAME",
    "LATEST_BILLING_ADDRESS3", "LATEST_BILLING_ADDRESS4", "LATEST_BILLING_ZIP",
]


def _view(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _EXPORT_COLUMNS if c in df.columns]
    return df[cols].sort_values(
        [SCORE_COL, "Spent"] if "Spent" in df.columns else [SCORE_COL],
        ascending=False,
    )


def _summary(scored: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, label, _apply, flag_col, _reason in active_signals():
        rows.append({
            "Signal": label,
            "Weight": SIGNAL_WEIGHTS.get(key, 0),
            "Customers flagged": int(scored[flag_col].fillna(False).sum()),
        })
    rows.append({"Signal": "— Any signal —", "Weight": "",
                 "Customers flagged": int((scored[COUNT_COL] > 0).sum())})
    rows.append({"Signal": "— Hidden VICs —", "Weight": "",
                 "Customers flagged": int(scored[HIDDEN_COL].sum())})
    return pd.DataFrame(rows)


def _autofit(writer: pd.ExcelWriter) -> None:
    """Widen columns roughly to their content for readability."""
    for sheet in writer.sheets.values():
        for col_cells in sheet.columns:
            width = max((len(str(c.value)) for c in col_cells if c.value is not None),
                        default=10)
            letter = col_cells[0].column_letter
            sheet.column_dimensions[letter].width = min(max(width + 2, 10), 60)
        sheet.freeze_panes = "A2"


def export_scored(
    scored: pd.DataFrame | None = None,
    df: pd.DataFrame | None = None,
    path: Path | str = EXPORT_FILE,
) -> Path:
    """Write the audit workbook. Pass an already-scored frame, or raw ``df``."""
    if scored is None:
        if df is None:
            raise ValueError("Provide either a scored frame or a raw df.")
        scored = score_customers(df)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    hidden = _view(scored[scored[HIDDEN_COL]])
    known = _view(scored[(scored[COUNT_COL] > 0) & (~scored[HIDDEN_COL])])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        hidden.to_excel(writer, sheet_name="Hidden VICs", index=False)
        known.to_excel(writer, sheet_name="Above threshold", index=False)
        _summary(scored).to_excel(writer, sheet_name="Signal summary", index=False)
        _autofit(writer)

    return path
