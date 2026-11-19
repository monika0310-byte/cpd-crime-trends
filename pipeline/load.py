"""Idempotent UPSERT of transformed rows into cpd_logs (COPY -> temp table -> ON CONFLICT)."""

import io
import os

import pandas as pd
from dotenv import load_dotenv
from prefect import task
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

TABLE = "cpd_logs"

# Column order here drives the DDL, the COPY and the UPSERT.
COLUMNS = {
    "id": "BIGINT PRIMARY KEY",
    "date_time": "TIMESTAMP NOT NULL",
    "type": "TEXT NOT NULL",
    "subtype": "TEXT",
    "location": "TEXT NOT NULL",
    "street": "TEXT NOT NULL",
    "description": "TEXT",
    "description_length": "INTEGER",
    "last_updated": "TIMESTAMP",
    "date": "DATE NOT NULL",
    "year": "SMALLINT NOT NULL",
    "month": "SMALLINT NOT NULL",
    "month_name": "TEXT NOT NULL",
    "day": "SMALLINT NOT NULL",
    "hour": "SMALLINT NOT NULL",
    "day_of_week": "TEXT NOT NULL",
    "dow_num": "SMALLINT NOT NULL",
    "is_weekend": "BOOLEAN NOT NULL",
    "time_of_day": "TEXT NOT NULL",
    "week_start": "DATE NOT NULL",
}

DDL = [
    f"CREATE TABLE IF NOT EXISTS {TABLE} (\n"
    + ",\n".join(f"    {col} {spec}" for col, spec in COLUMNS.items())
    + ",\n    loaded_at TIMESTAMP NOT NULL DEFAULT now()\n)",
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_date_time ON {TABLE} (date_time)",
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_type ON {TABLE} (type)",
    f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_street ON {TABLE} (street)",
]


def get_engine() -> Engine:
    load_dotenv()
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ["WAREHOUSE_USER"],
        password=os.environ["WAREHOUSE_PASSWORD"],
        host=os.getenv("WAREHOUSE_HOST", "localhost"),
        port=int(os.getenv("WAREHOUSE_PORT", "5433")),
        database=os.getenv("WAREHOUSE_DB", "cpd_insights"),
    )
    return create_engine(url, pool_pre_ping=True)


def _upsert_sql() -> str:
    cols = list(COLUMNS)
    col_list = ", ".join(cols)
    updates = ",\n        ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
    return f"""
        INSERT INTO {TABLE} ({col_list})
        SELECT {col_list} FROM stage_{TABLE}
        ON CONFLICT (id) DO UPDATE SET
        {updates},
        loaded_at = now()
    """


@task(name="load")
def load(df: pd.DataFrame) -> int:
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))

    buf = io.StringIO()
    df[list(COLUMNS)].to_csv(buf, index=False, header=False)
    buf.seek(0)

    raw = engine.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(
                f"CREATE TEMP TABLE stage_{TABLE} "
                f"(LIKE {TABLE} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            cur.copy_expert(
                f"COPY stage_{TABLE} ({', '.join(COLUMNS)}) FROM STDIN WITH (FORMAT csv)",
                buf,
            )
            cur.execute(_upsert_sql())
            upserted = cur.rowcount
            cur.execute(f"SELECT count(*) FROM {TABLE}")
            total = cur.fetchone()[0]
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()

    print(f"Upserted {upserted:,} rows; {TABLE} now holds {total:,} rows")
    return total
