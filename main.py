"""Entry point: load the data, score every customer, and rank hidden VICs.

Run with:  python main.py
"""
import pandas as pd

from scoring.combine import (
    COUNT_COL,
    HIDDEN_COL,
    REASONS_COL,
    SCORE_COL,
    SIGNALS,
    score_customers,
    top_hidden_vics,
)
from scoring.export import export_scored
from scoring.loader import load_data


def main() -> None:
    df = load_data()
    print(f"Loaded {len(df):,} customers x {df.shape[1]} columns\n")

    scored = score_customers(df)

    print("Customers fired on, per signal:")
    for _key, label, _apply, flag_col, _reason in SIGNALS:
        print(f"  - {label:<14} {scored[flag_col].fillna(False).sum():>4}")
    print(f"\nAny signal: {(scored[COUNT_COL] > 0).sum()}  |  "
          f"Hidden VICs (spend below threshold): {scored[HIDDEN_COL].sum()}")

    top = top_hidden_vics(scored, n=20)
    cols = ["Name", "Spent", "SEGMENT", SCORE_COL, COUNT_COL, REASONS_COL]
    print("\nTop 20 hidden VICs:")
    with pd.option_context(
        "display.max_columns", None, "display.width", 220, "display.max_colwidth", 60
    ):
        print(top[cols].to_string(index=False))

    path = export_scored(scored)
    print(f"\nExported full ranked workbook -> {path}")


if __name__ == "__main__":
    main()
