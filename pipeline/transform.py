"""Clean rows and derive the calendar / time-of-day / street features the dashboard uses."""

import pandas as pd
from prefect import task

TEXT_COLUMNS = ["type", "subtype", "location", "description"]

# Leading house / block numbers such as "330", "5XX", "12XX", "100-120", optional "BLOCK (OF)".
LEADING_NUMBER = r"^\s*\d+[0-9X]*(?:\s*-\s*\d+[0-9X]*)?\s+(?:BLOCK\s+(?:OF\s+)?)?"


def _time_of_day(hour: pd.Series) -> pd.Series:
    return pd.cut(
        hour,
        bins=[-1, 5, 11, 17, 23],
        labels=["Night", "Morning", "Afternoon", "Evening"],
    ).astype(str)


def _street(location: pd.Series) -> pd.Series:
    # "TARGET STORE / 564 MASSACHUSETTS AVE" -> "564 MASSACHUSETTS AVE" -> "MASSACHUSETTS AVE"
    street = location.str.split(" / ").str[-1]
    street = street.str.replace(LEADING_NUMBER, "", regex=True).str.strip()
    return street.where(street != "", location)


@task(name="transform")
def transform(df: pd.DataFrame) -> pd.DataFrame:
    before = len(df)
    # Keep the most recently updated version of each incident id.
    df = (
        df.dropna(subset=["id"])
        .sort_values("last_updated", na_position="first")
        .drop_duplicates(subset=["id"], keep="last")
        .copy()
    )
    df["id"] = df["id"].astype("int64")
    print(f"Dropped {before - len(df):,} invalid/duplicate rows; {len(df):,} remain")

    for col in TEXT_COLUMNS:
        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    df["type"] = df["type"].str.upper()
    df["location"] = df["location"].str.upper()

    ts = df["date_time"]
    df["date"] = ts.dt.date
    df["year"] = ts.dt.year
    df["month"] = ts.dt.month
    df["month_name"] = ts.dt.month_name()
    df["day"] = ts.dt.day
    df["hour"] = ts.dt.hour
    df["day_of_week"] = ts.dt.day_name()
    df["dow_num"] = ts.dt.dayofweek + 1  # 1 = Monday ... 7 = Sunday
    df["is_weekend"] = df["dow_num"] >= 6
    df["time_of_day"] = _time_of_day(df["hour"])
    df["week_start"] = (ts.dt.normalize() - pd.to_timedelta(ts.dt.dayofweek, unit="D")).dt.date
    df["street"] = _street(df["location"])
    df["description_length"] = df["description"].str.len()

    for col in ["subtype", "description"]:
        df[col] = df[col].replace("", None)

    print(f"Derived features for {len(df):,} rows; {df['street'].nunique():,} distinct streets")
    return df.sort_values("date_time").reset_index(drop=True)
