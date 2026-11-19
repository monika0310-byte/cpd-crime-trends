-- =====================================================================
-- Cambridge Crime Insights - Metabase native SQL cards (PostgreSQL 16)
-- Table: cpd_logs   (database cpd_insights)
--
-- Reference date: every "recent" window is anchored on MAX(date_time) in
-- cpd_logs, never on now(), so the dashboard stays meaningful even if the
-- city's feed lags behind the calendar.
--
-- Dashboard filters (Metabase text variables, each "Dropdown list" with
-- custom values). Every clause is wrapped in [[ ]] so the card still runs
-- when the filter is empty.
--   {{time_of_day}}  Night, Morning, Afternoon, Evening
--   {{day_kind}}     Weekday, Weekend
--   {{month_name}}   January ... December   (month of year, all years)
--
-- Each card header lists which filters it accepts. A filter is deliberately
-- left off a card when it would break the card's meaning (e.g. day_kind on
-- the weekend-share KPI would force it to 0% or 100%).
-- =====================================================================


-- ---------------------------------------------------------------------
-- [Top of dashboard, above tabs] TEXT CARD (Markdown, not SQL)
-- ---------------------------------------------------------------------
-- **Cambridge Crime Insights** - Cambridge Police Department *Daily Police Log*
-- (data.cambridgema.gov, dataset 3gki-wyrb), refreshed daily at 06:00 by a
-- Prefect ETL into PostgreSQL. "Latest" always means the newest record in the
-- data, not today.
-- **Pulse** - Is activity up or down right now, and what share happens at
-- night, on weekends, or ends in arrest?
-- **Rhythm** - When in the week and day do incidents cluster?
-- **Shifts** - What is changing: type mix, month-over-month swings, streets
-- heating up, and the language of reports.


-- =====================================================================
-- TAB 1: PULSE
-- =====================================================================

-- ---------------------------------------------------------------------
-- P1 | Tab: Pulse | Chart: Trend (KPI)
-- Title: Incidents - last 7 days vs prior 7
-- Filters: time_of_day, day_kind
-- Two rows (prior window, latest window); Metabase's Trend card shows the
-- latest value and the % change against the previous row.
-- ---------------------------------------------------------------------
WITH ref AS (
    SELECT MAX(date_time)::date AS ref_day FROM cpd_logs
),
windows AS (
    SELECT (ref_day - 13) AS window_start FROM ref
    UNION ALL
    SELECT (ref_day - 6) FROM ref
)
SELECT
    w.window_start,
    COUNT(l.id) AS incidents
FROM windows w
LEFT JOIN cpd_logs l
       ON l.date BETWEEN w.window_start AND w.window_start + 6
      [[AND l.time_of_day = {{time_of_day}}]]
      [[AND CASE WHEN l.is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
GROUP BY w.window_start
ORDER BY w.window_start;


-- ---------------------------------------------------------------------
-- P2 | Tab: Pulse | Chart: Number (KPI), style Percent
-- Title: Weekend share
-- Filters: time_of_day, month_name
-- ---------------------------------------------------------------------
SELECT
    AVG(CASE WHEN is_weekend THEN 1.0 ELSE 0.0 END) AS weekend_share
FROM cpd_logs
WHERE 1 = 1
  [[AND time_of_day = {{time_of_day}}]]
  [[AND month_name = {{month_name}}]];


-- ---------------------------------------------------------------------
-- P3 | Tab: Pulse | Chart: Number (KPI), style Percent
-- Title: Night-time share (00:00-05:59)
-- Filters: day_kind, month_name
-- ---------------------------------------------------------------------
SELECT
    AVG(CASE WHEN time_of_day = 'Night' THEN 1.0 ELSE 0.0 END) AS night_share
FROM cpd_logs
WHERE 1 = 1
  [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
  [[AND month_name = {{month_name}}]];


-- ---------------------------------------------------------------------
-- P4 | Tab: Pulse | Chart: Number (KPI), style Percent
-- Title: Arrest share
-- Filters: time_of_day, day_kind, month_name
-- ---------------------------------------------------------------------
SELECT
    AVG(CASE WHEN type = 'ARREST' THEN 1.0 ELSE 0.0 END) AS arrest_share
FROM cpd_logs
WHERE 1 = 1
  [[AND time_of_day = {{time_of_day}}]]
  [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
  [[AND month_name = {{month_name}}]];


-- ---------------------------------------------------------------------
-- P5 | Tab: Pulse | Chart: Line (full width), 2 series
-- Title: Daily incidents with 7-day moving average
-- Filters: time_of_day, day_kind, month_name
-- A calendar spine fills days with zero incidents so the moving average is
-- honest. day_kind / month_name filter the spine too, so the average is then
-- over the last 7 *matching* days.
-- ---------------------------------------------------------------------
WITH bounds AS (
    SELECT MIN(date) AS first_day, MAX(date_time)::date AS ref_day FROM cpd_logs
),
spine AS (
    SELECT gs::date AS day
    FROM bounds, generate_series(first_day, ref_day, INTERVAL '1 day') AS gs
),
daily AS (
    SELECT date AS day, COUNT(*) AS incidents
    FROM cpd_logs
    WHERE 1 = 1
      [[AND time_of_day = {{time_of_day}}]]
    GROUP BY date
),
filtered_spine AS (
    SELECT day
    FROM spine
    WHERE 1 = 1
      [[AND CASE WHEN EXTRACT(ISODOW FROM day) >= 6 THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
      [[AND TRIM(TO_CHAR(day, 'Month')) = {{month_name}}]]
)
SELECT
    s.day,
    COALESCE(d.incidents, 0) AS incidents,
    ROUND(
        AVG(COALESCE(d.incidents, 0)) OVER (ORDER BY s.day ROWS BETWEEN 6 PRECEDING AND CURRENT ROW),
        2
    ) AS moving_avg_7d
FROM filtered_spine s
LEFT JOIN daily d USING (day)
ORDER BY s.day;


-- =====================================================================
-- TAB 2: RHYTHM
-- =====================================================================

-- ---------------------------------------------------------------------
-- R1 | Tab: Rhythm | Chart: Pivot table / heatmap
-- Title: When incidents happen - day of week x hour
-- Filters: time_of_day, day_kind, month_name
-- Metabase only builds Pivot Table visualisations from GUI questions, so the
-- pivot is done here in SQL (one column per hour) and shown as a Table with
-- a conditional-formatting colour range across columns 00-23.
-- ---------------------------------------------------------------------
SELECT
    LEFT(day_of_week, 3) AS weekday,
    COUNT(*) FILTER (WHERE hour = 0)  AS "00",
    COUNT(*) FILTER (WHERE hour = 1)  AS "01",
    COUNT(*) FILTER (WHERE hour = 2)  AS "02",
    COUNT(*) FILTER (WHERE hour = 3)  AS "03",
    COUNT(*) FILTER (WHERE hour = 4)  AS "04",
    COUNT(*) FILTER (WHERE hour = 5)  AS "05",
    COUNT(*) FILTER (WHERE hour = 6)  AS "06",
    COUNT(*) FILTER (WHERE hour = 7)  AS "07",
    COUNT(*) FILTER (WHERE hour = 8)  AS "08",
    COUNT(*) FILTER (WHERE hour = 9)  AS "09",
    COUNT(*) FILTER (WHERE hour = 10) AS "10",
    COUNT(*) FILTER (WHERE hour = 11) AS "11",
    COUNT(*) FILTER (WHERE hour = 12) AS "12",
    COUNT(*) FILTER (WHERE hour = 13) AS "13",
    COUNT(*) FILTER (WHERE hour = 14) AS "14",
    COUNT(*) FILTER (WHERE hour = 15) AS "15",
    COUNT(*) FILTER (WHERE hour = 16) AS "16",
    COUNT(*) FILTER (WHERE hour = 17) AS "17",
    COUNT(*) FILTER (WHERE hour = 18) AS "18",
    COUNT(*) FILTER (WHERE hour = 19) AS "19",
    COUNT(*) FILTER (WHERE hour = 20) AS "20",
    COUNT(*) FILTER (WHERE hour = 21) AS "21",
    COUNT(*) FILTER (WHERE hour = 22) AS "22",
    COUNT(*) FILTER (WHERE hour = 23) AS "23",
    COUNT(*) AS total
FROM cpd_logs
WHERE 1 = 1
  [[AND time_of_day = {{time_of_day}}]]
  [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
  [[AND month_name = {{month_name}}]]
GROUP BY dow_num, day_of_week
ORDER BY dow_num;


-- ---------------------------------------------------------------------
-- R2 | Tab: Rhythm | Chart: Stacked bar
-- Title: Weekday vs weekend across the day
-- Filters: month_name   (the other two are this chart's own axes)
-- X = time_of_day (rows already in clock order), series = day_kind.
-- ---------------------------------------------------------------------
SELECT
    time_of_day,
    CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END AS day_kind,
    COUNT(*) AS incidents
FROM cpd_logs
WHERE 1 = 1
  [[AND month_name = {{month_name}}]]
GROUP BY time_of_day, day_kind
ORDER BY
    CASE time_of_day
        WHEN 'Night'     THEN 1
        WHEN 'Morning'   THEN 2
        WHEN 'Afternoon' THEN 3
        WHEN 'Evening'   THEN 4
    END,
    day_kind;


-- ---------------------------------------------------------------------
-- R3 | Tab: Rhythm | Chart: Bar (vertical columns), Mon -> Sun
-- Title: Incidents by day of week
-- Filters: time_of_day, day_kind, month_name
-- ---------------------------------------------------------------------
SELECT
    LEFT(day_of_week, 3) AS weekday,
    COUNT(*) AS incidents
FROM cpd_logs
WHERE 1 = 1
  [[AND time_of_day = {{time_of_day}}]]
  [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
  [[AND month_name = {{month_name}}]]
GROUP BY dow_num, day_of_week
ORDER BY dow_num;


-- =====================================================================
-- TAB 3: SHIFTS
-- =====================================================================

-- ---------------------------------------------------------------------
-- S1 | Tab: Shifts | Chart: Area, stacking "Stack - 100%"
-- Title: Incident type mix by week
-- Filters: time_of_day, day_kind, month_name
-- Rare types (SP, ASSIST, USE, ...) are folded into "Other".
-- ---------------------------------------------------------------------
SELECT
    week_start,
    CASE WHEN type IN ('INCIDENT', 'ARREST', 'TRAFFIC') THEN type ELSE 'OTHER' END AS type_group,
    COUNT(*) AS incidents
FROM cpd_logs
WHERE 1 = 1
  [[AND time_of_day = {{time_of_day}}]]
  [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
  [[AND month_name = {{month_name}}]]
GROUP BY week_start, type_group
ORDER BY week_start, type_group;


-- ---------------------------------------------------------------------
-- S2 | Tab: Shifts | Chart: Table (conditional formatting on pct_change)
-- Title: Month-over-month change
-- Filters: time_of_day, day_kind   (month_name off: LAG needs consecutive months)
-- The month containing MAX(date_time) is flagged as partial.
-- ---------------------------------------------------------------------
WITH ref AS (
    SELECT DATE_TRUNC('month', MAX(date_time))::date AS ref_month FROM cpd_logs
),
monthly AS (
    SELECT DATE_TRUNC('month', date_time)::date AS month_start, COUNT(*) AS incidents
    FROM cpd_logs
    WHERE 1 = 1
      [[AND time_of_day = {{time_of_day}}]]
      [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
    GROUP BY 1
),
with_lag AS (
    SELECT
        month_start,
        incidents,
        LAG(incidents) OVER (ORDER BY month_start) AS prev_incidents
    FROM monthly
)
SELECT
    TO_CHAR(w.month_start, 'YYYY-MM') AS month,
    w.incidents,
    w.prev_incidents,
    w.incidents - w.prev_incidents AS change,
    ROUND((w.incidents - w.prev_incidents)::numeric / NULLIF(w.prev_incidents, 0), 4) AS pct_change,
    CASE WHEN w.month_start = r.ref_month THEN 'partial' ELSE '' END AS note
FROM with_lag w
CROSS JOIN ref r
ORDER BY w.month_start DESC;


-- ---------------------------------------------------------------------
-- S3 | Tab: Shifts | Chart: Row (horizontal bar), stacked -> diverging
-- Title: Rising streets - latest full month vs previous
-- Filters: time_of_day, day_kind
-- "Latest full month" = the calendar month before the month of
-- MAX(date_time). Top 10 risers plus top 5 fallers for contrast; rising and
-- falling are separate series so they get separate colours.
-- ---------------------------------------------------------------------
WITH ref AS (
    SELECT DATE_TRUNC('month', MAX(date_time)) AS ref_month FROM cpd_logs
),
months AS (
    SELECT ref_month - INTERVAL '1 month' AS latest_month,
           ref_month - INTERVAL '2 month' AS previous_month,
           ref_month
    FROM ref
),
street_counts AS (
    SELECT
        l.street,
        COUNT(*) FILTER (WHERE l.date_time >= m.latest_month)  AS latest_n,
        COUNT(*) FILTER (WHERE l.date_time <  m.latest_month)  AS previous_n
    FROM cpd_logs l
    CROSS JOIN months m
    WHERE l.date_time >= m.previous_month
      AND l.date_time <  m.ref_month
      [[AND l.time_of_day = {{time_of_day}}]]
      [[AND CASE WHEN l.is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
    GROUP BY l.street
),
ranked AS (
    SELECT
        street, latest_n, previous_n,
        latest_n - previous_n AS change,
        ROW_NUMBER() OVER (ORDER BY latest_n - previous_n DESC, latest_n DESC, street) AS rise_rank,
        ROW_NUMBER() OVER (ORDER BY latest_n - previous_n ASC, previous_n DESC, street) AS fall_rank
    FROM street_counts
)
SELECT
    street,
    CASE WHEN change > 0 THEN change END AS rising,
    CASE WHEN change < 0 THEN change END AS falling,
    previous_n AS previous_month,
    latest_n   AS latest_month
FROM ranked
WHERE (rise_rank <= 10 AND change > 0)
   OR (fall_rank <= 5  AND change < 0)
ORDER BY change DESC, street;


-- ---------------------------------------------------------------------
-- S4 | Tab: Shifts | Chart: Row (horizontal bar)
-- Title: Top 20 words in incident descriptions
-- Filters: time_of_day, day_kind, month_name
-- Keeps words longer than 3 letters and drops English stopwords plus
-- report boilerplate that appears in almost every entry (edit the
-- boilerplate list to taste).
-- ---------------------------------------------------------------------
WITH stopwords(word) AS (
    SELECT UNNEST(ARRAY[
        -- English stopwords (> 3 letters)
        'that','this','with','from','were','have','been','they','their','them','there',
        'then','than','when','where','which','while','what','into','onto','about','after',
        'before','also','other','over','under','some','such','only','very','will','would',
        'could','should','being','both','each','more','most','your','upon','these','those',
        'through','during','again','once','here','himself','herself','itself','themselves',
        'because','until','against','between','above','below','does','doing','having',
        'just','same','said','within','without','along','another','back','away','later',
        -- report boilerplate
        'police','report','reported','reporting','responded','officers','officer','stated',
        'cambridge','block','street','massachusetts','past','party','person','individual'
    ])
),
words AS (
    SELECT REGEXP_SPLIT_TO_TABLE(LOWER(description), '[^a-z]+') AS word
    FROM cpd_logs
    WHERE description IS NOT NULL
      [[AND time_of_day = {{time_of_day}}]]
      [[AND CASE WHEN is_weekend THEN 'Weekend' ELSE 'Weekday' END = {{day_kind}}]]
      [[AND month_name = {{month_name}}]]
)
SELECT word, COUNT(*) AS mentions
FROM words
WHERE LENGTH(word) > 3
  AND word NOT IN (SELECT word FROM stopwords)
GROUP BY word
ORDER BY mentions DESC, word
LIMIT 20;
