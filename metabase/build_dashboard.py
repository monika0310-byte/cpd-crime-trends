"""Build or refresh the "Cambridge Crime Insights" Metabase dashboard through the REST API.

    python metabase/build_dashboard.py                 # delete + rebuild all cards and the dashboard
    python metabase/build_dashboard.py --refresh-text  # recompute only the header and "Key insights" text cards

Needs MB_EMAIL and MB_PASSWORD (Metabase admin login) in the environment; MB_URL defaults to http://localhost:3000.
On a fresh Metabase it also creates the admin account (MB_EMAIL / MB_PASSWORD), connects the warehouse
(reading WAREHOUSE_* from ../.env) and creates the "Cambridge Crime Insights" collection.
"""
import datetime
import os
import re
import sys
import uuid

import requests

MB = os.environ.get("MB_URL", "http://localhost:3000")
TEAL, ORANGE, GREY = "#0F766E", "#EA580C", "#9AA5B1"
TEAL_START = "#CCEBE7"  # lightest heatmap shade: still visibly teal, so low cells (e.g. Night) are not blank
NAME = "Cambridge Crime Insights"
s = requests.Session()


def call(method, path, ok404=False, **kw):
    r = s.request(method, MB + path, timeout=300, **kw)
    if ok404 and r.status_code in (404, 400):
        return None
    if not r.ok:
        raise SystemExit(f"{method} {path} -> {r.status_code}: {r.text[:1500]}")
    return r.json() if r.text else None


def bootstrap():
    """First-time setup on a fresh Metabase: admin account, warehouse connection, collection. Safe to re-run."""
    props = call("GET", "/api/session/properties")
    if not props.get("has-user-setup"):
        print("First-time Metabase setup ...")
        call("POST", "/api/setup", json={
            "token": props["setup-token"],
            "user": {"first_name": "Dashboard", "last_name": "Admin",
                     "email": os.environ["MB_EMAIL"], "password": os.environ["MB_PASSWORD"]},
            "prefs": {"site_name": NAME, "site_locale": "en", "allow_tracking": False},
        })
    s.headers["X-Metabase-Session"] = call(
        "POST", "/api/session", json={"username": os.environ["MB_EMAIL"], "password": os.environ["MB_PASSWORD"]})["id"]

    dbs = call("GET", "/api/database")["data"]
    db = next((d for d in dbs if d["name"] == "Cambridge Crime Warehouse"), None)
    if db is None:
        from dotenv import dotenv_values
        env = dotenv_values(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
        db = call("POST", "/api/database", json={
            "engine": "postgres", "name": "Cambridge Crime Warehouse", "is_full_sync": True,
            "details": {"host": "warehouse", "port": 5432, "dbname": env["WAREHOUSE_DB"],
                        "user": env["WAREHOUSE_USER"], "password": env["WAREHOUSE_PASSWORD"],
                        "ssl": False, "tunnel-enabled": False}})
        print("Added database 'Cambridge Crime Warehouse'")
    import time
    for _ in range(100):
        if call("GET", f"/api/database/{db['id']}").get("initial_sync_status") == "complete":
            break
        time.sleep(3)
    else:
        raise SystemExit("Metabase database sync did not finish")

    coll = next((c for c in call("GET", "/api/collection") if c["name"] == NAME), None)
    if coll is None:
        coll = call("POST", "/api/collection", json={"name": NAME, "color": TEAL})
    return db["id"], coll["id"]


DB, CID = bootstrap()


def dataset(sql):
    sql = re.sub(r"\[\[.*?\]\]", "", sql, flags=re.S)  # run a card's SQL with its optional filter clauses off
    j = call("POST", "/api/dataset", json={"database": DB, "type": "native", "native": {"query": sql}})
    assert not j.get("error"), j
    return j["data"]["rows"]


# ------------------------------------------------------------------ SQL (all counts COUNT(DISTINCT id))
DK = "[[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]"
DKL = DK.replace("is_weekend", "l.is_weekend")

# End (exclusive) of the last *complete* calendar month, anchored on MAX(date_time), never on today.
MONTH_END = """SELECT CASE WHEN (DATE_TRUNC('month', MAX(date_time)) + INTERVAL '1 month' - INTERVAL '1 day')::date <= MAX(date_time)::date
                 THEN DATE_TRUNC('month', MAX(date_time)) + INTERVAL '1 month'
                 ELSE DATE_TRUNC('month', MAX(date_time)) END AS end_excl FROM cpd_logs"""

Q = {}
Q["total"] = f"SELECT COUNT(DISTINCT id) AS total_incidents FROM cpd_logs WHERE 1 = 1 {DK}"

Q["trend"] = f"""WITH ref AS (SELECT MAX(date_time)::date AS ref_day FROM cpd_logs),
windows AS (SELECT ref_day - 13 AS window_start FROM ref UNION ALL SELECT ref_day - 6 FROM ref)
SELECT w.window_start, COUNT(DISTINCT l.id) AS incidents
FROM windows w
LEFT JOIN cpd_logs l ON l.date BETWEEN w.window_start AND w.window_start + 6 {DKL}
GROUP BY w.window_start ORDER BY w.window_start"""

Q["weekend"] = """SELECT COUNT(DISTINCT id) FILTER (WHERE is_weekend)::numeric / NULLIF(COUNT(DISTINCT id), 0) AS weekend_share
FROM cpd_logs"""

Q["arrest"] = f"""SELECT COUNT(DISTINCT id) FILTER (WHERE type = 'ARREST')::numeric / NULLIF(COUNT(DISTINCT id), 0) AS arrest_share
FROM cpd_logs WHERE 1 = 1 {DK}"""

Q["weekly"] = f"""WITH b AS (SELECT MIN(date_time)::date AS lo, MAX(date_time)::date AS hi FROM cpd_logs),
weekly AS (
    SELECT l.week_start, COUNT(DISTINCT l.id) AS incidents
    FROM cpd_logs l, b
    WHERE l.week_start >= b.lo AND l.week_start + 6 <= b.hi   -- complete Mon-Sun weeks only
      {DKL}
    GROUP BY l.week_start
)
SELECT week_start, incidents,
       CASE WHEN ROW_NUMBER() OVER (ORDER BY week_start) >= 4
            THEN ROUND(AVG(incidents) OVER (ORDER BY week_start ROWS BETWEEN 3 PRECEDING AND CURRENT ROW), 1) END AS moving_avg_4wk,
       ROUND(AVG(incidents) OVER (), 1) AS average
FROM weekly ORDER BY week_start"""

Q["yoy"] = f"""WITH lim AS ({MONTH_END})
SELECT TO_CHAR(l.date_time, 'Mon') AS month, l.year::text AS year, COUNT(DISTINCT l.id) AS incidents
FROM cpd_logs l, lim
WHERE l.date_time < lim.end_excl {DKL}
GROUP BY l.month, TO_CHAR(l.date_time, 'Mon'), l.year
ORDER BY l.month, l.year"""

Q["streets"] = f"""WITH lim AS ({MONTH_END}),
sc AS (
    SELECT l.street,
           COUNT(DISTINCT l.id) FILTER (WHERE l.date_time >= lim.end_excl - INTERVAL '1 month') AS latest_n,
           COUNT(DISTINCT l.id) FILTER (WHERE l.date_time <  lim.end_excl - INTERVAL '1 month') AS prev_n
    FROM cpd_logs l, lim
    WHERE l.date_time >= lim.end_excl - INTERVAL '2 month' AND l.date_time < lim.end_excl {DKL}
    GROUP BY l.street
),
q AS (   -- streets with >= 3 incidents in either month and some change
    SELECT street, latest_n, prev_n, latest_n - prev_n AS change
    FROM sc WHERE (latest_n >= 3 OR prev_n >= 3) AND latest_n <> prev_n
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (ORDER BY change DESC, street) AS rise_rank,
              ROW_NUMBER() OVER (ORDER BY change ASC, street)  AS fall_rank
    FROM q
),
picked AS (
    SELECT street, change, prev_n, latest_n FROM ranked
    WHERE (change > 0 AND rise_rank <= 5) OR (change < 0 AND fall_rank <= 5)
),
result AS (
    SELECT street, change, prev_n AS previous_month, latest_n AS latest_month FROM picked WHERE (SELECT COUNT(*) FROM q) >= 3
    UNION ALL
    SELECT 'Not enough data for this filter', 0, NULL::bigint, NULL::bigint WHERE (SELECT COUNT(*) FROM q) < 3
)
SELECT street,
       CASE WHEN change > 0 THEN change END AS increase,
       CASE WHEN change < 0 THEN change END AS decrease,
       previous_month, latest_month
FROM result ORDER BY change DESC, street"""

Q["dow"] = f"""SELECT LEFT(day_of_week, 3) AS weekday, COUNT(DISTINCT id) AS incidents
FROM cpd_logs WHERE 1 = 1 {DK}
GROUP BY dow_num, day_of_week ORDER BY dow_num"""

Q["tod"] = f"""SELECT time_of_day, CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_kind, COUNT(DISTINCT id) AS incidents
FROM cpd_logs WHERE 1 = 1 {DK}
GROUP BY 1, 2
ORDER BY CASE time_of_day WHEN 'Night' THEN 1 WHEN 'Morning' THEN 2 WHEN 'Afternoon' THEN 3 ELSE 4 END, 2"""

Q["heat"] = f"""SELECT LEFT(day_of_week, 3) AS weekday,
       COUNT(DISTINCT id) FILTER (WHERE time_of_day = 'Night')     AS "Night",
       COUNT(DISTINCT id) FILTER (WHERE time_of_day = 'Morning')   AS "Morning",
       COUNT(DISTINCT id) FILTER (WHERE time_of_day = 'Afternoon') AS "Afternoon",
       COUNT(DISTINCT id) FILTER (WHERE time_of_day = 'Evening')   AS "Evening"
FROM cpd_logs WHERE 1 = 1 {DK}
GROUP BY dow_num, day_of_week ORDER BY dow_num"""


# ------------------------------------------------------------------ text cards computed from the data
def fmt_date(d):
    x = datetime.date.fromisoformat(d[:10])
    return f"{x.strftime('%b')} {x.day}, {x.year}"


def text_cards():
    first, last, total = dataset("SELECT MIN(date_time)::date, MAX(date_time)::date, COUNT(DISTINCT id) FROM cpd_logs")[0]
    header = f"**Cambridge Police Daily Log** · {fmt_date(first)} to {fmt_date(last)} · {total:,} incidents · refreshed daily"

    dow = dict(dataset(Q["dow"]))
    full = {"Mon": "Monday", "Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday",
            "Sat": "Saturday", "Sun": "Sunday"}
    top_d, low_d = max(dow, key=dow.get), min(dow, key=dow.get)

    tod = {}
    for t, _, n in dataset(Q["tod"]):
        tod[t] = tod.get(t, 0) + n
    tt = sum(tod.values())
    top_t, low_t = max(tod, key=tod.get), min(tod, key=tod.get)
    hours = {"Night": "midnight-6am", "Morning": "6am-noon", "Afternoon": "noon-6pm", "Evening": "6pm-midnight"}

    wk = dataset(Q["weekly"])
    latest, earlier = wk[-1][2], wk[-5][2]
    ch = (latest - earlier) / earlier
    direction = "flat" if abs(ch) < 0.02 else ("rising" if ch > 0 else "falling")
    word = {"flat": "roughly flat at", "rising": "rising to", "falling": "falling to"}[direction]

    ym = {}
    for m, y, n in dataset(Q["yoy"]):
        ym.setdefault(y, {})[m] = n
    cur, prev = max(ym), str(int(max(ym)) - 1)
    months = [m for m in ym[cur] if m in ym.get(prev, {})]
    a, b = sum(ym[cur][m] for m in months), sum(ym[prev][m] for m in months)
    span = f"{months[0]}-{months[-1]}" if len(months) > 1 else months[0]

    insights = "\n".join([
        "**Key insights**",
        "",
        f"- **Busiest day:** {full[top_d]} ({dow[top_d]:,} incidents); {full[low_d]} is the quietest ({dow[low_d]:,}).",
        f"- **Busiest time:** {top_t.lower()} ({hours[top_t]}) holds {tod[top_t] / tt:.1%} of incidents; {low_t.lower()} only {tod[low_t] / tt:.1%}.",
        f"- **Trend:** the 4-week average is {word} {latest:.1f} incidents a week "
        f"({ch:+.1%} vs 4 weeks earlier; overall weekly average {wk[0][3]:.1f}).",
        f"- **Vs last year:** {span} {cur} has {a:,} incidents vs {b:,} in {span} {prev} ({(a - b) / b:+.1%}).",
    ])
    return header, insights


# ------------------------------------------------------------------ visualisation settings
def pct(c):
    return {f'["name","{c}"]': {"number_style": "percent", "decimals": 1}}


def ax(x, y):
    return {"graph.x_axis.title_text": x, "graph.y_axis.title_text": y}


HEAT_COLS = ["Night", "Morning", "Afternoon", "Evening"]
HEAT_MAX = max(max(r[1:]) for r in dataset(Q["heat"]))
HEAT_MAX = ((HEAT_MAX // 50) + 1) * 50

SPEC = [  # key, title, description, display, viz
    ("total", "Total incidents", "Every distinct incident in the log.", "scalar",
     {"scalar.field": "total_incidents"}),
    ("trend", "Last 7 days vs previous 7",
     "Incidents in the 7 days up to the newest record vs the 7 days before; green = fewer, red = more.",
     "smartscalar", {"scalar.field": "incidents", "scalar.switch_positive_negative": True}),
    ("weekend", "Weekend share",
     "Share of all incidents that happened on a Saturday or Sunday. Not affected by the filter.", "scalar",
     {"scalar.field": "weekend_share", "column_settings": pct("weekend_share")}),
    ("arrest", "Arrest share", "Share of incidents that were logged as arrests.", "scalar",
     {"scalar.field": "arrest_share", "column_settings": pct("arrest_share")}),
    ("weekly", "Is crime rising or falling?",
     "Incidents per complete week (thin teal), the 4-week moving average (thick orange) and the overall average (grey dashed).",
     "line", {"graph.dimensions": ["week_start"], "graph.metrics": ["incidents", "moving_avg_4wk", "average"],
              "line.marker_enabled": False, "graph.x_axis.scale": "timeseries", **ax("Week starting", "Incidents per week"),
              "series_settings": {
                  "incidents": {"color": TEAL, "line.size": "S", "title": "Weekly incidents"},
                  "moving_avg_4wk": {"color": ORANGE, "line.size": "L", "title": "4-week average"},
                  "average": {"color": GREY, "line.size": "S", "line.style": "dashed", "title": "Average"}}}),
    ("yoy", "This year vs last year",
     "Incidents per month, 2025 (grey dashed) against 2026 (teal); complete months only.", "line",
     {"graph.dimensions": ["month", "year"], "graph.metrics": ["incidents"], "line.marker_enabled": False,
      **ax("Month", "Incidents per month"),
      "series_settings": {"2025": {"color": GREY, "line.style": "dashed", "line.size": "M"},
                          "2026": {"color": TEAL, "line.style": "solid", "line.size": "L"}}}),
    ("streets", "Which streets changed most last month?",
     "Top 5 rises (orange) and top 5 falls (teal) in incidents, latest full month vs the month before; streets with 3+ incidents in either month.",
     "row", {"graph.dimensions": ["street"], "graph.metrics": ["increase", "decrease"], "graph.show_values": True,
             "stackable.stack_type": "stacked", **ax("", "Change in incidents"),
             "column_settings": {'["name","increase"]': {"prefix": "+"}},
             "series_settings": {"increase": {"color": ORANGE, "title": "Increase"},
                                 "decrease": {"color": TEAL, "title": "Decrease"}}}),
    ("dow", "Which day is busiest?", "Total incidents for each day of the week.", "bar",
     {"graph.dimensions": ["weekday"], "graph.metrics": ["incidents"], **ax("Day of week", "Incidents"),
      "series_settings": {"incidents": {"color": TEAL}}}),
    ("tod", "Which time of day is busiest?",
     "Incidents by time of day, weekday (teal) vs weekend (orange). Night 0-5, Morning 6-11, Afternoon 12-17, Evening 18-23.",
     "bar", {"graph.dimensions": ["time_of_day", "day_kind"], "graph.metrics": ["incidents"],
             "stackable.stack_type": "stacked", **ax("Time of day", "Incidents"),
             "graph.x_axis.axis_enabled": True,
             "series_settings": {"Weekday": {"color": TEAL}, "Weekend": {"color": ORANGE}}}),
    ("heat", "When do incidents cluster?",
     "Incidents by day of week and time of day; darker teal = more incidents.", "table",
     {"table.column_formatting": [{"columns": HEAT_COLS, "type": "range", "colors": [TEAL_START, TEAL],
                                   "min_type": "custom", "min_value": 0, "max_type": "custom", "max_value": HEAT_MAX,
                                   "operator": "=", "value": "", "highlight_row": False}]}),
]


def virtual_text(dc_id, text, row, h):
    return {"id": dc_id, "card_id": None, "row": row, "col": 0, "size_x": 24, "size_y": h,
            "visualization_settings": {"virtual_card": {"name": None, "display": "text", "visualization_settings": {},
                                                        "dataset_query": {}, "archived": False},
                                       "text": text},
            "parameter_mappings": []}


def refresh_text():
    header, insights = text_cards()
    dash = next(d for d in call("GET", f"/api/collection/{CID}/items?models=dashboard")["data"] if d["name"] == NAME)
    d = call("GET", f"/api/dashboard/{dash['id']}")
    out = []
    for dc in d["dashcards"]:
        vs = dc["visualization_settings"]
        if dc["card_id"] is None and "text" in vs:
            vs = {**vs, "text": insights if vs["text"].startswith("**Key insights**") else header}
        out.append({k: dc[k] for k in ("id", "card_id", "dashboard_tab_id", "row", "col", "size_x", "size_y",
                                       "parameter_mappings")} | {"visualization_settings": vs})
    call("PUT", f"/api/dashboard/{dash['id']}", json={"dashcards": out})
    print("Refreshed header and Key insights on", f"{MB}/dashboard/{dash['id']}")
    print(header)
    print(insights)


def build():
    for it in call("GET", f"/api/collection/{CID}/items?models=dashboard")["data"]:
        call("DELETE", f"/api/dashboard/{it['id']}")
    for it in call("GET", f"/api/collection/{CID}/items?models=card")["data"]:
        call("PUT", f"/api/card/{it['id']}", json={"archived": True})
        call("DELETE", f"/api/card/{it['id']}", ok404=True)

    header, insights = text_cards()
    cards = {}
    for key, title, desc, display, viz in SPEC:
        tags = {t: {"id": str(uuid.uuid4()), "name": t, "display-name": "Weekday / weekend", "type": "text"}
                for t in sorted(set(re.findall(r"\{\{(\w+)\}\}", Q[key])))}
        cid = call("POST", "/api/card", json={
            "name": title, "description": desc, "collection_id": CID, "display": display,
            "visualization_settings": viz,
            "dataset_query": {"database": DB, "type": "native", "native": {"query": Q[key], "template-tags": tags}},
            "parameters": [{"id": v["id"], "type": "category", "name": v["display-name"], "slug": k,
                            "target": ["variable", ["template-tag", k]]} for k, v in tags.items()],
        })["id"]
        cards[key] = {"id": cid, "tags": list(tags)}

    n = [0]

    def nid():
        n[0] -= 1
        return n[0]

    def dc(key, row, col, w, h):
        c = cards[key]
        return {"id": nid(), "card_id": c["id"], "row": row, "col": col, "size_x": w, "size_y": h,
                "visualization_settings": {},
                "parameter_mappings": [{"parameter_id": t, "card_id": c["id"],
                                        "target": ["variable", ["template-tag", t]]} for t in c["tags"]]}

    dash = call("POST", "/api/dashboard", json={"name": NAME, "collection_id": CID,
                                                "description": "Crime trends from the Cambridge Police Daily Log."})
    call("PUT", f"/api/dashboard/{dash['id']}", json={
        "width": "full",
        "parameters": [{"id": "day_kind", "name": "Weekday / weekend", "slug": "day_kind", "type": "string/=",
                        "sectionId": "string", "values_query_type": "list", "values_source_type": "static-list",
                        "values_source_config": {"values": ["Weekday", "Weekend"]}}],
        "dashcards": [
            virtual_text(nid(), header, 0, 2),
            virtual_text(nid(), insights, 2, 4),
            dc("total", 6, 0, 6, 3), dc("trend", 6, 6, 6, 3), dc("weekend", 6, 12, 6, 3), dc("arrest", 6, 18, 6, 3),
            dc("weekly", 9, 0, 24, 7),
            dc("yoy", 16, 0, 12, 7), dc("streets", 16, 12, 12, 7),
            dc("dow", 23, 0, 7, 7), dc("tod", 23, 7, 9, 7), dc("heat", 23, 16, 8, 7)]})
    print("Built", f"{MB}/dashboard/{dash['id']}")
    print(header)
    print(insights)


if __name__ == "__main__":
    refresh_text() if "--refresh-text" in sys.argv else build()
