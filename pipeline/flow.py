"""Prefect flow wiring.

    python -m pipeline.flow           # run once
    python -m pipeline.flow --serve   # long-running process, scheduled daily at 06:00
"""

import argparse

from prefect import flow
from prefect.schedules import Cron

from pipeline.extract import extract
from pipeline.load import load
from pipeline.transform import transform
from pipeline.validate import validate


@flow(name="cambridge_crime_etl", log_prints=True)
def cambridge_crime_etl() -> int:
    raw = extract()
    clean = validate(raw)
    features = transform(clean)
    total = load(features)
    print(f"cambridge_crime_etl finished: cpd_logs = {total:,} rows")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Cambridge crime ETL")
    parser.add_argument("--serve", action="store_true", help="serve with a daily 06:00 schedule")
    args = parser.parse_args()

    if args.serve:
        cambridge_crime_etl.serve(
            name="cambridge-crime-daily",
            schedule=Cron("0 6 * * *", timezone="America/New_York"),
        )
    else:
        cambridge_crime_etl()


if __name__ == "__main__":
    main()
