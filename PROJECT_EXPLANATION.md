# Cambridge Crime Insights: Project Explanation

Written for: a student presenting this project and answering questions about it.

> **Important note before you present.** Two files in this folder are out of date:
> `README.md` and `sql/dashboard_queries.sql` describe an **earlier 3-tab dashboard (12 cards)**.
> The dashboard that is actually running now is a **one-page, 10-card dashboard**, and its SQL lives inside
> `metabase/build_dashboard.py`. This document explains the **current** version. If someone asks to see the
> SQL for the dashboard, open `metabase/build_dashboard.py` (the `Q[...]` entries).

---

## 1. One-paragraph summary

The Cambridge Police Department publishes a "Daily Police Log" on the city's open-data website. It lists every
incident the police responded to: when it happened, what type it was, which street, and a short written
description. This project **automatically downloads that log, checks it, cleans it, adds useful extra columns
(like "is it a weekend?" or "was it night?"), and stores it in a PostgreSQL database**. A dashboard tool called
**Metabase** then reads the database and shows charts that answer simple questions: *Is crime going up or down?
Which day and time are busiest? Which streets changed the most last month?* Everything runs on a laptop using
Docker, and the whole download-and-store process can run by itself every morning.

---

## 2. The big picture

```
Cambridge open-data website (Socrata API)
            |
            v
      1. EXTRACT      download all rows            (pipeline/extract.py)
            |
            v
      2. VALIDATE     check the data is sane       (pipeline/validate.py)
            |
            v
      3. TRANSFORM    clean + add new columns      (pipeline/transform.py)
            |
            v
      4. LOAD         save into the database       (pipeline/load.py)
            |
            v
   PostgreSQL database "cpd_insights", table "cpd_logs"   (Docker container: cpd_warehouse)
            |
            v
   Metabase dashboard "Cambridge Crime Insights"          (Docker container: cpd_metabase, http://localhost:3000)

   Steps 1-4 are tied together and scheduled by a Prefect "flow"  (pipeline/flow.py)
```

In plain words:

1. **Extract**: ask the city's website for every row of the police log.
2. **Validate**: make sure the columns are the ones we expect and nothing important is missing.
3. **Transform**: remove duplicates, tidy the text, and create new columns.
4. **Load**: put the rows into a database table. If a row already exists, update it instead of adding it twice.
5. **Visualise**: Metabase runs SQL queries on that table and draws the charts.

This pattern is called **ETL** (Extract, Transform, Load). It is the standard way to move data from a source
into a place where it can be analysed.

---

## 3. Tools used and why

| Tool | What it is | What it does in this project |
|---|---|---|
| **Python** | A programming language | Runs the whole pipeline. |
| **sodapy** | A Python library for "Socrata" websites | Downloads data from the Cambridge open-data portal. Socrata is the company whose platform the city uses. |
| **pandas** | A Python library for tables of data | Holds the data in memory (a "DataFrame") and does the cleaning and the new columns. |
| **Prefect** | A workflow tool | Runs the four steps in order, retries a step if it fails, writes logs, and can run the pipeline on a schedule (daily at 06:00). |
| **PostgreSQL** | A database | Stores the cleaned data in the table `cpd_logs`. Metabase reads from it. |
| **SQLAlchemy + psycopg2** | Python libraries for databases | Let Python connect to PostgreSQL (SQLAlchemy builds the connection, psycopg2 is the actual driver). |
| **python-dotenv** | A small Python library | Reads passwords and settings from the `.env` file so they are not written inside the code. |
| **Docker** | A tool that runs programs in isolated "containers" | Runs PostgreSQL and Metabase without installing them on Windows. |
| **Docker Compose** | A tool that starts several containers from one file | `docker-compose.yml` describes all three containers; one command (`docker compose up -d`) starts them. |
| **Metabase** | A dashboard / business-intelligence tool | Connects to the database, runs SQL, and shows the charts. It is also controlled through its REST API by `build_dashboard.py`. |

---

## 4. File-by-file walkthrough

### Folder layout

```
cpd-crime-trends/
|-- .env                      secret settings (passwords, API token). NOT shared.
|-- .env.example              the same file with fake values, safe to share
|-- .gitignore                tells Git to ignore .env, .venv and cache files
|-- requirements.txt          list of Python libraries to install
|-- docker-compose.yml        defines the 3 containers
|-- pipeline/
|   |-- __init__.py           marks the folder as a Python package
|   |-- extract.py            step 1
|   |-- validate.py           step 2
|   |-- transform.py          step 3
|   |-- load.py               step 4
|   |-- flow.py               ties the steps together (Prefect)
|-- metabase/
|   |-- build_dashboard.py    builds the dashboard through Metabase's API
|-- sql/
|   |-- dashboard_queries.sql SQL of the EARLIER 3-tab dashboard (out of date)
|-- README.md                 setup guide (partly describes the earlier dashboard)
```

### `.env`

A plain text file of `NAME=value` lines. The code and Docker read these values, so **no password is hard-coded
anywhere**. It contains:

- `SOCRATA_APP_TOKEN`: an optional key for the city's website. With it, the website does not slow down ("throttle") our downloads.
- `WAREHOUSE_USER`, `WAREHOUSE_PASSWORD`, `WAREHOUSE_DB`: the login and name of the main database (`cpd_insights`).
- `WAREHOUSE_HOST=localhost`, `WAREHOUSE_PORT=5433`: where Python finds that database (see section 6).
- `MB_APPDB_USER`, `MB_APPDB_PASSWORD`, `MB_APPDB_NAME`: login for the *second* database that Metabase uses for itself.
- `PREFECT_SERVER_ANALYTICS_ENABLED=false`: turns off Prefect's usage-statistics sending, which also removed a harmless error message we saw.

The real values in this file are secrets. Do not show them on a slide or put them on GitHub.

### `.env.example`

A copy of `.env` with fake passwords (`change-me`). It is the "template" someone else copies to create their own
`.env`. It is safe to share.

### `.gitignore`

Lists things Git must not upload: `.env` (secrets), `.venv/` (the big Python environment folder), and
`__pycache__/` / `*.pyc` (Python's temporary files).

### `requirements.txt`

The six Python libraries the project needs: `pandas`, `sodapy`, `python-dotenv`, `SQLAlchemy`, `psycopg2-binary`,
`prefect`. `pip install -r requirements.txt` installs them all.

### `docker-compose.yml`

Describes three containers on one private network.

```yaml
services:
  warehouse:                  # the main database
    image: postgres:16
    container_name: cpd_warehouse
    environment:              # database name/user/password come from .env
      POSTGRES_USER: ${WAREHOUSE_USER}
      ...
    ports:
      - "5433:5432"           # computer's port 5433 -> container's port 5432
    volumes:
      - warehouse_data:/var/lib/postgresql/data
    healthcheck: ...
```

- **`image: postgres:16`**: use the official PostgreSQL version 16 program.
- **`${WAREHOUSE_USER}`**: "take this value from `.env`".
- **`ports: "5433:5432"`**: opens a door from your computer (port 5433) into the container (port 5432). Python uses this door.
- **`volumes: warehouse_data`**: a **named volume** is a storage area Docker keeps on disk. Without it, deleting the container would delete all the data. With it, the data survives restarts.
- **`healthcheck`**: every 10 seconds Docker runs `pg_isready` to ask "is the database ready?". The units (`10s`) matter on Windows. Other services can wait for "healthy".

```yaml
  mb_appdb:                   # Metabase's own private database
    image: postgres:16
    container_name: cpd_mb_appdb
```

Metabase needs somewhere to store *its own* things: user accounts, saved questions, dashboards. That is this
second database. It is kept separate from the crime data on purpose.

```yaml
  metabase:
    image: metabase/metabase:latest
    ports: ["3000:3000"]      # open http://localhost:3000
    environment:
      MB_DB_HOST: mb_appdb    # Metabase stores its settings in mb_appdb
      ...
    depends_on:
      mb_appdb:  { condition: service_healthy }
      warehouse: { condition: service_healthy }
```

`depends_on ... service_healthy` means "do not start Metabase until both databases are ready". Metabase takes
1 to 2 minutes to start. At the bottom, `networks: cpd_net` is one private network all three containers join, and
`volumes:` declares the two named storage areas.

### `pipeline/__init__.py`

One line. Its existence tells Python that `pipeline/` is a package, so we can write `python -m pipeline.flow`.

### `pipeline/extract.py` (step 1: download)

```python
@task(name="extract", retries=3, retry_delay_seconds=[15, 30, 60])
def extract() -> pd.DataFrame:
```
- `@task` makes this function a Prefect task. `retries=3` means if the download fails (internet hiccup), Prefect
  tries again up to 3 times, waiting 15, then 30, then 60 seconds.

```python
load_dotenv()
token = os.getenv("SOCRATA_APP_TOKEN") or None
```
- Reads `.env` and gets the app token. If it is empty, we use `None` and download anonymously (slower limits).

```python
with Socrata(DOMAIN, token, timeout=60) as client:
    records = list(client.get_all(DATASET_ID, limit=PAGE_SIZE, order=":id"))
```
- Connects to `data.cambridgema.gov`. `timeout=60` means "wait up to 60 seconds for an answer".
- `DATASET_ID = "3gki-wyrb"` is the ID of the Daily Police Log.
- `get_all` downloads page by page (5,000 rows each) until everything is fetched.
- **`order=":id"`** is the most important detail. See section 6.

```python
df = pd.DataFrame.from_records(records)
```
- Turns the list of records into a pandas table.

### `pipeline/validate.py` (step 2: check)

```python
EXPECTED_COLUMNS = {"date_time", "id", "type", "subtype", "location", "last_updated", "description"}
REQUIRED_NON_NULL = ["date_time", "type", "location"]
```
- The seven columns we expect, and the three that must never be empty.

Inside `validate`:
- `if df.empty: raise ValueError(...)` stops the pipeline if nothing was downloaded.
- If any expected column is **missing**, it stops with an error. We do not carry on with data we do not understand.
- `df["id"] = pd.to_numeric(df["id"], errors="coerce")`: turns ids into numbers. `errors="coerce"` means a bad value becomes "missing" (NaN) instead of crashing. Those rows are removed in the next step.
- `pd.to_datetime(..., errors="coerce")`: same idea for the dates.
- It counts nulls (empty values), non-numeric ids and duplicates, then **prints a data-quality summary** (you see this in the Prefect logs).
- If `date_time`, `type` or `location` has any empty value, it raises an error, so a broken dataset never reaches the database.

This is a **"fail loudly"** design: better to stop and tell you than to quietly store bad data.

### `pipeline/transform.py` (step 3: clean and add columns)

**Remove bad and duplicate rows**
```python
df = (df.dropna(subset=["id"])
        .sort_values("last_updated", na_position="first")
        .drop_duplicates(subset=["id"], keep="last"))
```
- Drop rows with no valid id.
- Sort by `last_updated`, then keep the **last** copy of each id. So if the same incident appears twice, we keep the most recently updated version.

**Clean text**
- For `type`, `subtype`, `location`, `description`: fill empties, collapse repeated spaces, trim the ends. `type` and `location` become UPPER CASE so "Main St" and "MAIN ST" are the same.

**New columns** (explained fully in section 5):
```python
ts = df["date_time"]
df["date"] = ts.dt.date
df["day_of_week"] = ts.dt.day_name()
df["dow_num"] = ts.dt.dayofweek + 1        # Monday = 1 ... Sunday = 7
df["is_weekend"] = df["dow_num"] >= 6
df["time_of_day"] = _time_of_day(df["hour"])
df["week_start"] = ... # the Monday of that week
df["street"] = _street(df["location"])
```
- `_time_of_day` uses `pd.cut` with the boundaries 0-5, 6-11, 12-17, 18-23 and names them Night, Morning, Afternoon, Evening.
- `_street` removes house numbers using a *regular expression* (a pattern):
  `LEADING_NUMBER = r"^\s*\d+[0-9X]*(...)"`. It also keeps only the part after `" / "`, so
  `TARGET STORE / 564 MASSACHUSETTS AVE` becomes `MASSACHUSETTS AVE`. The police hide exact numbers as `5XX`,
  and the pattern handles that too.

### `pipeline/load.py` (step 4: save to the database)

**The column list**
```python
COLUMNS = { "id": "BIGINT PRIMARY KEY", "date_time": "TIMESTAMP NOT NULL", ... }
```
- One dictionary of column name and database type. It is used to build the table, the copy command and the
  update command, so they can never get out of sync.
- `PRIMARY KEY` on `id` means every incident id can exist only once. `NOT NULL` means that column must be filled.

**Table and indexes**
```python
CREATE TABLE IF NOT EXISTS cpd_logs (...)
CREATE INDEX IF NOT EXISTS ix_cpd_logs_date_time ON cpd_logs (date_time) ...
```
- `IF NOT EXISTS` makes it safe to run every day.
- **Indexes** on `date_time`, `type` and `street` work like the index of a book: they make searching those
  columns faster.

**The connection**
```python
url = URL.create(drivername="postgresql+psycopg2", username=..., password=..., host=..., port=..., database=...)
```
- `URL.create` builds the connection address from separate pieces. This is safer than gluing a text string
  together, because a password with symbols like `@` or `:` still works.

**The upsert**
```python
cur.execute("CREATE TEMP TABLE stage_cpd_logs (LIKE cpd_logs ...) ON COMMIT DROP")
cur.copy_expert("COPY stage_cpd_logs (...) FROM STDIN WITH (FORMAT csv)", buf)
cur.execute("INSERT INTO cpd_logs ... SELECT ... FROM stage_cpd_logs
             ON CONFLICT (id) DO UPDATE SET ...")
```
1. Create a **temporary** table (it disappears automatically at the end).
2. **COPY** all rows into it in one fast bulk operation.
3. Move them into the real table with `INSERT ... ON CONFLICT (id) DO UPDATE`. In plain words: *"insert the row;
   if that id already exists, update the existing row instead."* This is an **upsert** (update + insert).
4. Print how many rows were upserted and how many the table now holds. If anything fails, `rollback()` undoes it.

### `pipeline/flow.py` (the conductor)

```python
@flow(name="cambridge_crime_etl", log_prints=True)
def cambridge_crime_etl():
    raw = extract()
    clean = validate(raw)
    features = transform(clean)
    total = load(features)
```
- A Prefect **flow** is a workflow made of tasks. This one runs the four steps in order, passing the table along.
- `log_prints=True` means every `print()` appears in Prefect's logs.

```python
if args.serve:
    cambridge_crime_etl.serve(name="cambridge-crime-daily", schedule=Cron("0 6 * * *", timezone="America/New_York"))
else:
    cambridge_crime_etl()
```
- `python -m pipeline.flow` runs once. `python -m pipeline.flow --serve` stays running and starts the flow every day
  at 06:00 Cambridge time. `"0 6 * * *"` is a *cron* expression meaning "minute 0, hour 6, every day".

### `metabase/build_dashboard.py` (builds the dashboard automatically)

Instead of clicking everything by hand, this script talks to Metabase's **REST API** (a set of web addresses a
program can call).

- Logs in using `MB_EMAIL` and `MB_PASSWORD` (set as environment variables).
- Holds the **SQL of each card** in the dictionary `Q`.
- Holds each card's chart type, colours and description in the list `SPEC`.
- `build()` deletes the old dashboard and cards, creates the 10 cards, creates the dashboard, wires the filter,
  and places the cards on a grid. It sets the dashboard to full width.
- `text_cards()` runs queries to get the **real numbers** for the header and the "Key insights" box, so those
  texts are written from the data, not typed by hand.
- `python metabase/build_dashboard.py --refresh-text` updates only those two text boxes (use it after new data arrives).
- Needs two things to exist first in Metabase: a database connection named **"Cambridge Crime Warehouse"** and a
  collection (folder) named **"Cambridge Crime Insights"**. See section 8.

### `sql/dashboard_queries.sql`

The SQL for the **earlier** 12-card, 3-tab dashboard. It is still a good example of the SQL techniques used, but
it is **not** what the live dashboard runs. Keep it as history, or delete it and re-export the current queries.

### `README.md`

A setup guide with the project layout, setup commands, and Metabase instructions. The setup and layout parts are
still correct. The dashboard-building part describes the earlier 3-tab version. The last section compares this
project with your original notebook.

---

## 5. The data

**Source:** Cambridge Police Department *Daily Police Log*, dataset `3gki-wyrb` on `data.cambridgema.gov`.

**Size:** **12,493 rows** (one row per incident). **Date range:** **1 January 2025 to 15 October 2026**.
After the load, `cpd_logs` has 12,493 rows and about 1,291 different streets.

**Type breakdown:** INCIDENT 11,867 (about 95%), ARREST 398, TRAFFIC 203, and a handful of other types.

### Original columns (from the city)

| Column | Meaning |
|---|---|
| `id` | A unique number for each incident. |
| `date_time` | When the incident happened. |
| `type` | The broad category: INCIDENT, ARREST, TRAFFIC, etc. |
| `subtype` | The more specific charge or reason, e.g. "LARCENY FROM BUILDING C266 S20". |
| `location` | Where it happened (street, sometimes with a business name). House numbers are partly hidden, e.g. `5XX MASSACHUSETTS AVE`. |
| `description` | A short sentence or two written by the police. |
| `last_updated` | When the city last edited that row. |

### Columns we created in `transform.py` (and why)

| New column | What it is | Why we made it |
|---|---|---|
| `date` | Just the calendar date (no time). | Easy to group by day. |
| `year`, `month`, `day` | The numbers pulled out of the date. | Easy to filter and compare years and months. |
| `month_name` | "January", "February", ... | Readable labels. |
| `hour` | Hour of the day, 0 to 23. | Needed for time-of-day groups. |
| `day_of_week` | "Monday" ... "Sunday". | For the busiest-day chart. |
| `dow_num` | 1 = Monday ... 7 = Sunday. | Lets SQL sort days in real order (Mon to Sun) instead of alphabetically. |
| `is_weekend` | True for Saturday and Sunday. | Weekend vs weekday comparisons and the filter. |
| `time_of_day` | Night (0-5), Morning (6-11), Afternoon (12-17), Evening (18-23). | Turns 24 hours into 4 easy-to-read groups. |
| `week_start` | The Monday of the week that date belongs to. | Groups incidents by week. |
| `street` | `location` with house numbers and business names removed. | Lets us compare streets fairly, because `330 RIVER ST` and `10 RIVER ST` both become `RIVER ST`. |
| `description_length` | Number of characters in the description. | A simple extra measure of how detailed the report is. |
| `loaded_at` | When the row was last written to our database (added by the database). | Helps check when data was refreshed. |

---

## 6. Important design decisions

### Why upsert instead of "replace"?
The simple way is `to_sql(if_exists="replace")`, which **deletes the whole table and rebuilds it** every day.
That is risky: if the load fails halfway, you could be left with an empty or broken table, and it destroys the
indexes and the primary key. An **upsert** only adds new rows and updates changed ones, in one safe transaction
(all-or-nothing). Running the pipeline twice gives the same result. This property is called **idempotent**. It
also means the city can correct an old incident and our copy updates automatically.

### Why `order=":id"` when extracting?
The website returns data in pages, like pages of a book. If we do not say how to order the rows, the website can
shuffle them between page requests. Then some rows appear twice and others are **never returned at all**, and
nothing warns you. In our testing, a run without ordering produced **394 to 459 duplicate rows** and silently
missed the same number of real rows. Ordering by `:id` (the website's internal row number) keeps the pages stable.
Now we get exactly 12,493 rows with **zero duplicates**.

### Why are partial weeks and months excluded?
The data ends on **Thursday 15 October 2026**. The week of 12 to 18 October only has 4 days of data, and October
only has 15 days. If we drew them, the line would **fall off a cliff at the end**, and it would look like crime
suddenly dropped when really the period was just unfinished. So:
- Weekly chart: only complete Monday-to-Sunday weeks. We also drop the first partial week, because the data starts on a Wednesday (1 January 2025).
- Monthly charts and the streets card: only complete months. October 2026 is left out; the last full month is September.

We checked that nothing is lost: the weekly total (12,321) plus the two dropped partial weeks (94 and 78) equals
12,493, and the monthly total (12,201) plus partial October (292) also equals 12,493.

### Why use `MAX(date_time)` instead of today's date?
The newest record is 15 October 2026, but "today" is later. The city's feed lags behind the calendar. If we
measured "last 7 days" from today, the window would contain **no data at all**. Anchoring on the newest record in
the table always gives a meaningful answer.

### Why `COUNT(DISTINCT id)`?
It counts each incident exactly once, even if a duplicate row ever sneaked in. It is a safety net.

### Why Metabase uses `warehouse:5432` but Python uses `localhost:5433`
They are in **different places**.
- **Python runs on your Windows computer**, outside Docker. To reach a container it uses the "door" Docker opened
  on your computer: `localhost` port **5433** (`ports: "5433:5432"`). We chose 5433 so it never clashes with a
  PostgreSQL you may already have on 5432.
- **Metabase runs inside Docker**, on the private network `cpd_net`. Inside that network containers find each
  other by **service name**, and they talk to the container's real port **5432**. Also, inside a container
  `localhost` means *that container itself*, so using `localhost` there would point Metabase at itself and fail.

So: from your computer, `localhost:5433`. From inside Docker, `warehouse:5432`. Same database, two addresses.

### Other decisions
- **Secrets in `.env`**, never in code, and `.env` is in `.gitignore`.
- **Two separate databases**: one for crime data, one for Metabase's own settings, so dashboards never mix with data.
- **Validation fails loudly** rather than loading bad data.
- **Healthchecks and `depends_on`** so things start in the right order.

---

## 7. The dashboard

**URL:** `http://localhost:3000/dashboard/5`. One page, no tabs, teal / orange / grey colours.
**Filter:** "Weekday / weekend" (applies to every card except Weekend share).
**Top text box:** "Cambridge Police Daily Log · Jan 1, 2025 to Oct 15, 2026 · 12,493 incidents · refreshed daily", followed by a **Key insights** box written from the data.

All numbers below are what the cards showed when we checked them.

### Row 1: four number cards

**1. Total incidents** (number). *How many incidents are in the log?*
SQL: `COUNT(DISTINCT id)` over the whole table. **Result: 12,493.** (9,644 on weekdays, 2,849 on weekends.)

**2. Last 7 days vs previous 7** (trend card). *Is it busier or quieter than last week?*
SQL: finds the newest date, then counts incidents in two windows of 7 days: the 7 days up to that date, and the
7 days before. The trend card shows the percentage change. Green means fewer incidents, red means more.
**Result: 133 vs 132, a change of about +0.8%.** That is basically flat.

**3. Weekend share** (percent). *What share of incidents happen on a Saturday or Sunday?*
SQL: weekend incidents divided by all incidents. **Result: 22.8%.** Weekends are 2 of 7 days (28.6%), so
weekends are **quieter** than weekdays per day.
This card ignores the filter (its description says so), because filtering by weekday would make it 0% or 100%.

**4. Arrest share** (percent). *What share of incidents are arrests?*
SQL: incidents where `type = 'ARREST'` divided by all incidents. **Result: 3.2%.** Most log entries are
reports, not arrests.

### Row 2: full width

**5. Is crime rising or falling?** (line chart). *Over time, is the weekly total going up or down?*
SQL: counts incidents per complete week, then uses a **window function** `AVG(...) OVER (ORDER BY week_start ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)`
to average each week with the 3 before it (a **4-week moving average**). A third column is the overall average.
Thin teal = weekly count, thick orange = 4-week average, grey dashed = overall average.
**Result:** 92 complete weeks. The overall average is **133.9** a week. The latest 4-week average is **139.3**, about
**+0.7%** compared with 4 weeks earlier, so the trend is **roughly flat**.

### Row 3: two cards

**6. This year vs last year** (two lines). *Is 2026 higher or lower than 2025, month by month?*
SQL: counts incidents per month and year, only for complete months, so 2026 stops at September.
Grey dashed = 2025, thick teal = 2026.
**Result:** January to September 2026 has **5,183** incidents vs **5,264** in the same months of 2025, about
**1.5% lower**. For example, January was 479 in 2026 vs 553 in 2025.

**7. Which streets changed most last month?** (horizontal bars). *Which streets got worse or better?*
SQL: counts incidents per street in the last full month (September) and the month before (August). Subtracts to
get the change. Keeps only streets with **at least 3 incidents in either month**. Then takes the **top 5
increases** (orange) and **top 5 decreases** (teal). If fewer than 3 streets qualify under the current filter,
it shows one row saying **"Not enough data for this filter"** instead of one misleading bar.
**Result (September vs August):**
- Increases: Alewife Brook Pkwy +7, Rindge Ave +7, Central Sq +4, Broadway +3, Clary St +3.
- Decreases: Massachusetts Ave -9, White St -8, Cambridgeside Pl -7, River St -6, Main St -4.

Small streets have small numbers, so one or two incidents can look like a big jump. Treat this card as "where to
look", not as proof of a trend.

### Row 4: three cards

**8. Which day is busiest?** (column chart). *Which weekday has the most incidents?*
SQL: counts incidents per day of week, ordered by `dow_num` so it shows Monday to Sunday.
**Result:** Friday is busiest (**1,967**), then Wednesday 1,940, Monday 1,933, Tuesday 1,924, Thursday 1,880.
Saturday has 1,530 and Sunday is quietest with **1,319**. Weekdays are fairly even; weekends are clearly lower.

**9. Which time of day is busiest?** (stacked bar). *When in the day do incidents happen, weekday vs weekend?*
SQL: counts incidents per `time_of_day` and per weekday/weekend. Weekday is teal, weekend is orange.
**Result:** Afternoon is the busiest by far: **5,477 incidents, 43.8%** of all. Morning has 3,246, evening 3,024 and
night only **746 (6.0%)**.

**10. When do incidents cluster?** (heatmap table). *Which day-and-time combinations are busiest?*
SQL: for each weekday, counts incidents in each of the four time-of-day groups (using `COUNT(...) FILTER (WHERE ...)`
to make one column per group). Metabase colours the cells from light to dark teal, so darker means more.
**Result:** the darkest cells are **weekday afternoons** (about 830 to 890 incidents each). Weekday nights are the
lightest (about 80 to 120). Interestingly, **weekend nights (138 each) are busier than weekday nights**, even
though weekends are quieter overall.

### What the dashboard tells us overall
Crime reports in Cambridge are **steady**: about 130 to 140 a week, with no strong rise or fall, and slightly
lower in 2026 than in 2025 so far. Incidents happen mostly in the **afternoon** and on **weekdays**; weekends and
nights are quieter, although night incidents are relatively more common at weekends.

---

## 8. How to run it from scratch on a new computer

You need: **Windows or Mac/Linux with Docker Desktop**, **Python 3.12 or newer**, and an internet connection.

1. **Get the project folder** onto the computer (copy it or clone it from Git). Open a terminal in that folder.
2. **Create your settings file.** Copy `.env.example` to `.env` and replace the passwords:
   `Copy-Item .env.example .env` (PowerShell). Optionally paste a free Socrata app token into `SOCRATA_APP_TOKEN`.
3. **Create the Python environment and install libraries:**
   ```
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
   If PowerShell refuses to activate, run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.
4. **Start Docker Desktop**, then start the containers:
   ```
   docker compose up -d
   docker compose ps
   ```
   Wait until `cpd_warehouse` shows **healthy** (Metabase takes 1 to 2 minutes).
5. **Run the pipeline once:**
   ```
   python -m pipeline.flow
   ```
   You should see about 12,493 rows loaded. Check with:
   `docker exec cpd_warehouse psql -U <WAREHOUSE_USER> -d cpd_insights -c "SELECT count(*) FROM cpd_logs;"`
6. **Set up Metabase.** Open `http://localhost:3000`. Create the admin account (any email and password you choose).
7. **Connect the database in Metabase** (Admin settings, Databases, Add database, PostgreSQL):
   - Display name: **Cambridge Crime Warehouse** (this exact name; the script looks for it)
   - Host: `warehouse`, Port: `5432`, Database: `cpd_insights`
   - Username and password: the `WAREHOUSE_USER` and `WAREHOUSE_PASSWORD` from your `.env`
   - Wait for the sync to finish so the table `cpd_logs` appears.
8. **Create a collection** (a folder) named exactly **Cambridge Crime Insights** (the script needs it to exist).
9. **Build the dashboard** with the script, using the admin login from step 6:
   ```
   $env:MB_EMAIL = "you@example.com"
   $env:MB_PASSWORD = "your-metabase-password"
   python metabase/build_dashboard.py
   ```
   It prints the dashboard URL.
10. **(Optional) Run it every day automatically.** Leave this running: `python -m pipeline.flow --serve`.
    After new data arrives, run `python metabase/build_dashboard.py --refresh-text` to refresh the two text boxes.

To stop everything: `docker compose down`. Your data stays. `docker compose down -v` also **deletes the data**.

---

## 9. Limitations and future improvements

**Limitations**
- **Only reported incidents.** The log shows what police responded to or recorded. Crime that nobody reported is not here. More reports could mean more reporting, not more crime.
- **Data delay.** The newest record is 15 October 2026, around three weeks behind the calendar. The city updates it with a lag, so the dashboard is never truly "live".
- **No map.** We only have a street name, not exact coordinates, so there is no map view.
- **Street names are approximate.** House numbers are hidden by the police, and business names are stripped by our rule, so "street" is only street-level. One long street (like Massachusetts Ave) is counted as a single place.
- **Small numbers can mislead.** Many streets have only a few incidents, so month-to-month changes can be noise.
- **Categories are lopsided.** About 95% of rows are type INCIDENT, so type-based analysis is limited.
- **Full reload each day.** The pipeline downloads the whole dataset every time (about 12,000 rows is small, but it would not scale to millions).
- **Static text boxes.** The "Key insights" text is written when the script runs; it does not update by itself.
- **Setup is partly manual.** Creating the Metabase admin, adding the database and creating the collection are done by hand once.
- **`--serve` must stay running.** The 06:00 schedule only works while that terminal/process is alive and the computer is on.
- **`metabase/metabase:latest`** can change over time and could one day change how the API behaves; pinning a version would be safer.
- **Out-of-date files.** `README.md` (dashboard section) and `sql/dashboard_queries.sql` still describe the earlier 3-tab design.
- **No automatic tests or alerts** if the pipeline fails.

**Future improvements**
- Add a **map** by geocoding street names into coordinates.
- Load only **new or changed rows** (incremental load, using `last_updated`) instead of everything.
- Add **automated tests** and email/Slack alerts for pipeline failures.
- Add **crime-type filters** and a text-mining view of the descriptions.
- Join other data (weather, university term dates, population) to explain patterns.
- **Auto-create** the Metabase database connection and collection in `build_dashboard.py`, and pin the Metabase version.
- Move the pipeline into a container so one `docker compose up` does everything.
- Update the README and replace `sql/dashboard_queries.sql` with the current queries.

---

## 10. Fifteen likely viva / presentation questions

**1. What does your project do, in one sentence?**
It automatically downloads the Cambridge Police daily log, cleans it, stores it in a PostgreSQL database, and shows crime trends on a Metabase dashboard.

**2. What is ETL?**
Extract, Transform, Load: take data from a source, clean and reshape it, and load it into a database where it can be analysed.

**3. Where does the data come from?**
The City of Cambridge open-data portal, dataset `3gki-wyrb` (Daily Police Log), accessed through the Socrata API using the `sodapy` library.

**4. Why did you use Prefect?**
It runs the four steps in order, retries a failed download automatically, keeps logs, and can schedule the pipeline daily at 06:00. Without it I would have to run scripts by hand.

**5. Why Docker and Docker Compose?**
Docker lets me run PostgreSQL and Metabase without installing them on my computer, and everyone gets the same versions. Compose starts all three containers with one command and one config file.

**6. What is an upsert and why did you use it?**
Insert a row if it is new, update it if the id already exists. It means I can run the pipeline every day without duplicates and without deleting the table, and corrected records update themselves.

**7. Why do you order by `:id` when downloading?**
Data comes in pages. Without a fixed order, pages can overlap or skip rows silently. In my tests that caused about 400 to 460 duplicates and the same number of missing rows. Ordering by `:id` gives exactly 12,493 rows with no duplicates.

**8. How do you make sure the data is good?**
The validate step checks that all seven expected columns exist, converts ids and dates, and stops the pipeline with an error if date, type or location is empty. It also prints a data-quality summary.

**9. What new columns did you create?**
Date parts (year, month, day, hour), `day_of_week` and `dow_num`, `is_weekend`, `time_of_day` (Night, Morning, Afternoon, Evening), `week_start`, a cleaned `street`, and `description_length`. They make grouping and filtering simple.

**10. Why does Metabase use `warehouse:5432` but Python uses `localhost:5433`?**
Python runs on my computer and enters Docker through the published port 5433. Metabase runs inside Docker's private network, where containers reach each other by service name `warehouse` on the real port 5432. Inside a container, `localhost` would mean itself.

**11. Why did you leave out the latest week and month?**
They are incomplete (the data ends on 15 October), so they would look like a sudden crash in crime. I only chart complete weeks and months, and I checked that the dropped parts plus the charted parts add up to the 12,493 total.

**12. Why `MAX(date_time)` instead of today's date?**
The data lags behind the calendar by weeks. Using today would give an empty "last 7 days". The newest record in the table is the honest reference point.

**13. What are the main findings?**
Crime reports are steady, about 134 a week on average, and slightly lower in 2026 than in 2025 so far (-1.5% for January to September). Friday is the busiest day and Sunday the quietest. Afternoons hold about 44% of incidents, nights only 6%. Weekends have fewer incidents overall.

**14. What are the limits of this data?**
It only contains reported incidents, it lags by weeks, house numbers are hidden so there is no map, and most rows are the generic type INCIDENT. More reports does not always mean more crime. Small streets give noisy percentages.

**15. How would you improve it?**
Load only new rows instead of everything, add a map using coordinates, add automated tests and failure alerts, auto-create the Metabase setup in the script, and combine the data with other sources such as weather or events.

---

*Tip for the presentation: demo the flow in this order. (1) show `docker compose ps` with three healthy containers, (2) run `python -m pipeline.flow` and point at the data-quality summary and row count, (3) open the dashboard and use the Weekday / weekend filter, (4) read the Key insights box.*
