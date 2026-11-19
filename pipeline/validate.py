"""Schema and data-quality gate. Fails loudly on anything the dashboard can't survive."""

import pandas as pd
from prefect import task

EXPECTED_COLUMNS = {"date_time", "id", "type", "subtype", "location", "last_updated", "description"}
REQUIRED_NON_NULL = ["date_time", "type", "location"]


@task(name="validate")
def validate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError("Extract returned no rows.")

    missing = EXPECTED_COLUMNS - set(df.columns)
    extra = set(df.columns) - EXPECTED_COLUMNS
    if missing:
        raise ValueError(f"Missing expected columns: {sorted(missing)}")

    df = df[sorted(EXPECTED_COLUMNS)].copy()

    # Non-numeric ids become NaN and are dropped in transform.
    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce")
    df["last_updated"] = pd.to_datetime(df["last_updated"], errors="coerce")

    nulls = {col: int(df[col].isna().sum()) for col in REQUIRED_NON_NULL}
    bad_ids = int(df["id"].isna().sum())

    print("Data-quality summary")
    print(f"  rows               : {len(df):,}")
    print(f"  unexpected columns : {sorted(extra) or 'none'}")
    print(f"  non-numeric ids    : {bad_ids:,} (dropped in transform)")
    print(f"  duplicate ids      : {int(df['id'].duplicated().sum()):,} (dropped in transform)")
    for col, n in nulls.items():
        print(f"  null {col:<14}: {n:,}")
    print(f"  date range         : {df['date_time'].min()} -> {df['date_time'].max()}")

    failing = {col: n for col, n in nulls.items() if n}
    if failing:
        raise ValueError(f"Required columns contain nulls/unparseable values: {failing}")
    return df
