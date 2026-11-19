# Deployment (AWS EC2, Sydney)

Live dashboard: **http://<SERVER_IP>:3000** (log in with the Metabase admin account created during deployment).
Public, no-login link (read-only): **http://<SERVER_IP>:3000/public/dashboard/<PUBLIC_SHARE_UUID>** (see section 9).

No passwords are stored in this file. Server secrets live only in `~/cpd-crime-trends/.env` on the server (mode 600).

## 1. Architecture

```
                         internet
                            |  (security group: only 22 SSH and 3000 Metabase are open)
          +-----------------+------------------------------------------+
          |  EC2 t3.small, Ubuntu 24.04, 2 GB RAM + 2 GB swap          |
          |                                                            |
          |  Docker (compose project "cpd-crime-insights", network cpd_net)
          |    metabase    :3000  (public)   JVM capped at -Xmx1g      |
          |    mb_appdb           (private)  Metabase's own Postgres   |
          |    warehouse   127.0.0.1:5433 -> 5432  (crime data)        |
          |                                                            |
          |  systemd                                                   |
          |    cpd-prefect.service  Prefect server, 127.0.0.1:4200     |
          |    cpd-etl.service      python -m pipeline.flow --serve    |
          |                         runs the ETL daily at 06:00 New York
          |  cron                                                      |
          |    Sundays 03:00  scripts/backup.sh -> ~/backups           |
          +------------------------------------------------------------+
```

- The pipeline (Python venv at `~/cpd-crime-trends/.venv`) downloads the Cambridge Police Daily Log, validates it, transforms it, and UPSERTs it into `warehouse` (table `cpd_logs`). Metabase reads that table.
- Python reaches the database at `localhost:5433` (loopback only). Metabase reaches it at `warehouse:5432` over the private Docker network.
- **Ports 5432, 5433 and 4200 are never exposed to the internet.** The security group must never open them.
- All three containers use `restart: unless-stopped`; both systemd services are enabled, so everything returns after a reboot (tested).
- Why a Prefect server? `--serve` on its own uses a temporary server that cannot run schedules. `cpd-prefect` is a small always-on server so the 06:00 schedule really fires.

Server layout:

| Path | What |
|---|---|
| `~/cpd-crime-trends/` | the project |
| `~/cpd-crime-trends/.env` | production secrets (mode 600, not in git) |
| `~/cpd-crime-trends/.venv/` | Python 3.12 virtual environment |
| `~/backups/` | weekly database dumps (newest 8 kept) and `backup.log` |
| `/etc/systemd/system/cpd-*.service` | service files (copies in `deploy/`) |

## 2. SSH in

From Windows PowerShell:

```powershell
ssh -i <KEY_FILE> ubuntu@<SERVER_IP>
```

Keep the `.pem` private: never commit, upload or share it. If Windows says the permissions are too open:

```powershell
icacls <KEY_FILE> /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

## 3. Check status and view logs

```bash
cd ~/cpd-crime-trends

# containers
docker compose ps
docker compose logs --tail 100 metabase        # or warehouse / mb_appdb
docker compose logs -f metabase                # follow live (Ctrl+C to stop)

# ETL scheduler
systemctl status cpd-etl cpd-prefect --no-pager
journalctl -u cpd-etl -n 100 --no-pager        # add -f to follow
journalctl -u cpd-prefect -n 50 --no-pager

# upcoming and past pipeline runs
curl -s -X POST http://127.0.0.1:4200/api/flow_runs/filter -H 'Content-Type: application/json' \
  -d '{"flow_runs":{"state":{"type":{"any_":["SCHEDULED"]}}},"sort":"EXPECTED_START_TIME_ASC","limit":3}'

# health, memory, disk, backups
curl -s http://localhost:3000/api/health
free -m; df -h /
tail -5 ~/backups/backup.log; ls -lh ~/backups

# row count in the warehouse
set -a; . ./.env; set +a
docker exec cpd_warehouse psql -U "$WAREHOUSE_USER" -d "$WAREHOUSE_DB" -c "SELECT count(*), max(date_time) FROM cpd_logs;"
```

## 4. Restart things

```bash
cd ~/cpd-crime-trends
docker compose restart metabase          # one container
docker compose restart                   # all containers
sudo systemctl restart cpd-etl           # the scheduler
sudo systemctl restart cpd-prefect cpd-etl
sudo reboot                              # whole server; everything starts by itself
```

Run the pipeline immediately (outside the schedule):

```bash
cd ~/cpd-crime-trends && .venv/bin/python -m pipeline.flow
```

## 5. Update the code

There is no git remote, so push from your laptop. In PowerShell, in the project folder:

```powershell
$k = "<KEY_FILE>"
tar -czf $env:TEMP\project.tar.gz --exclude=.venv --exclude=__pycache__ --exclude=.git --exclude=.env --exclude="*.pem" .
scp -i $k $env:TEMP\project.tar.gz ubuntu@<SERVER_IP>:/tmp/
ssh -i $k ubuntu@<SERVER_IP> "tar -xzf /tmp/project.tar.gz -C ~/cpd-crime-trends && rm /tmp/project.tar.gz"
```

(`.env` is excluded, so the server's production passwords are never overwritten.) Then on the server, depending on what changed:

```bash
cd ~/cpd-crime-trends
.venv/bin/pip install -r requirements.txt     # if requirements.txt changed
docker compose up -d                          # if docker-compose.yml changed
sudo systemctl restart cpd-etl                # if anything under pipeline/ changed
```

Rebuild or refresh the dashboard (needs the Metabase admin login):

```bash
export MB_EMAIL=<admin email> MB_PASSWORD='<admin password>'
.venv/bin/python metabase/build_dashboard.py                 # delete + rebuild all cards and the dashboard
.venv/bin/python metabase/build_dashboard.py --refresh-text  # only the header and Key insights text
```

Forgot the Metabase admin password:

```bash
docker exec cpd_metabase java -jar /app/metabase.jar reset-password <admin email>
```

## 6. Restore a backup

Backups are gzipped SQL dumps of the `cpd_insights` database in `~/backups/`. Take one by hand any time with `~/cpd-crime-trends/scripts/backup.sh`. The restore procedure was tested (12,845 rows restored and matched live).

```bash
cd ~/cpd-crime-trends
ls -lh ~/backups
BACKUP=~/backups/cpd_insights_YYYYMMDD_HHMMSS.sql.gz      # pick one

# Safe: restore into a scratch database first and inspect it
docker exec cpd_warehouse sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE restore_check"'
zcat $BACKUP | docker exec -i cpd_warehouse sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d restore_check'
docker exec cpd_warehouse sh -c 'psql -U "$POSTGRES_USER" -d restore_check -c "SELECT count(*) FROM cpd_logs"'
docker exec cpd_warehouse sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE restore_check"'

# Real restore: replace the live table (the pipeline refills it daily anyway)
sudo systemctl stop cpd-etl
docker exec cpd_warehouse sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP TABLE IF EXISTS cpd_logs"'
zcat $BACKUP | docker exec -i cpd_warehouse sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
sudo systemctl start cpd-etl
```

Note: the backup covers the crime data only. The Metabase dashboards live in `mb_appdb`, but they can be rebuilt any time with `metabase/build_dashboard.py`. The crime data can also be re-downloaded by running the pipeline.

Backups are stored on the same server disk. To keep a copy elsewhere, copy one to your laptop:

```powershell
scp -i <KEY_FILE> ubuntu@<SERVER_IP>:~/backups/cpd_insights_*.sql.gz .
```

## 7. Stop everything to avoid charges

| Goal | Action | What still costs money |
|---|---|---|
| Pause compute | **Stop** the instance in the EC2 console (Instances, Instance state, Stop). Containers and services start again by themselves when you start it. | The EBS disk (about 20 GB). A public IPv4 address is still billed while attached. If the IP is not an Elastic IP, it changes when the instance is restarted, so the dashboard URL changes. |
| Stop all charges | **Terminate** the instance, then delete any leftover EBS volumes and release any **Elastic IP** in the console. | Nothing (but the data is gone, so download a backup first). |

Stopping only the containers (`docker compose down`) does **not** stop AWS charges; the instance keeps running. To stop the app but keep the server: `docker compose down` and `sudo systemctl disable --now cpd-etl cpd-prefect`. To keep the data, never use `docker compose down -v` (that deletes the volumes).

Also set a billing alarm: AWS Billing, Budgets, create a monthly cost budget with email alerts.

## 8. Estimated monthly cost (approximate)

Running 24/7 in ap-southeast-2 at on-demand prices (check the AWS pricing page for exact current rates):

| Item | Estimate |
|---|---|
| t3.small instance (about US$0.026/hour) | about US$19 |
| EBS gp3 disk, about 20 GB | about US$2 |
| Public IPv4 address (US$0.005/hour) | about US$4 |
| Data transfer (light use) | under US$1 |
| **Total** | **about US$25 per month** |

Free-tier credits or a stopped instance would reduce this. Stopped, you pay roughly US$2 to US$6 per month for the disk and IP.

## 9. Public share link (no login)

**URL:** http://<SERVER_IP>:3000/public/dashboard/<PUBLIC_SHARE_UUID>

Anyone who has this URL can open the "Cambridge Crime Insights" dashboard and use its **Weekday / weekend** dropdown without an account. The link is the only protection, so treat it like a password-lite: share it only with people you want to see the data. The dashboard shows aggregate crime statistics (counts, streets, times), not individual records.

What was verified (with no login session):

- The page loads and all 10 data cards return data, both unfiltered and with the Weekday and Weekend filter values (the filter changes the numbers; "Weekend share" intentionally ignores it).
- It is the **only** public object: no other dashboard, question or action is public, and static embedding is off.
- It is read-only. Anonymous requests to edit or delete the dashboard, list or create questions, list databases, or run ad-hoc SQL are all refused (HTTP 401), and write attempts against the public endpoint return 404.
- Note: the HTTP port is plain `http` (no HTTPS), so traffic is not encrypted. Each viewer runs the dashboard queries on the 2 GB server, so a very large audience could slow it.

### Disable it

Pick one (log in as the Metabase admin first):

1. **This dashboard only (browser):** open the dashboard, click the **Sharing** (share) icon, and switch **Public link** off.
2. **This dashboard only (API):**
   ```powershell
   # get a session token, then remove the link
   $s = (Invoke-RestMethod -Method Post http://<SERVER_IP>:3000/api/session -ContentType application/json -Body (@{username="<admin email>";password="<admin password>"} | ConvertTo-Json)).id
   Invoke-RestMethod -Method Delete http://<SERVER_IP>:3000/api/dashboard/2/public_link -Headers @{"X-Metabase-Session"=$s}
   ```
3. **All public sharing, instance-wide (browser):** Admin settings, **Public sharing**, switch **Enable public sharing** off. (API: `PUT /api/setting/enable-public-sharing` with body `{"value": false}`.)

To **rotate** the link (the old URL stops working): disable the dashboard's public link as above, then enable it again; Metabase issues a new random URL. Update this section with the new one.
