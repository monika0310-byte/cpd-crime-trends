"""Pull the full Cambridge Police Daily Log from the Socrata API."""

import os

import pandas as pd
from dotenv import load_dotenv
from prefect import task
from sodapy import Socrata

DOMAIN = "data.cambridgema.gov"
DATASET_ID = "3gki-wyrb"  # Daily Police Log
PAGE_SIZE = 5000


@task(name="extract", retries=3, retry_delay_seconds=[15, 30, 60])
def extract() -> pd.DataFrame:
    load_dotenv()
    token = os.getenv("SOCRATA_APP_TOKEN") or None  # empty string -> anonymous
    if token is None:
        print("No SOCRATA_APP_TOKEN set; using anonymous (throttled) access.")

    with Socrata(DOMAIN, token, timeout=60) as client:
        # Offset paging is only stable with an explicit order; without it pages
        # overlap and silently skip rows. ":id" is Socrata's internal row id.
        records = list(client.get_all(DATASET_ID, limit=PAGE_SIZE, order=":id"))

    df = pd.DataFrame.from_records(records)
    print(f"Extracted {len(df):,} rows from {DOMAIN}/{DATASET_ID}")
    return df
