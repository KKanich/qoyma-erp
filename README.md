# Qoyma ERP - Grocery Store Management System

Qoyma is a lightweight, offline-capable ERP system designed for small grocery stores (such as «Bereke» in Almaty). Built with Python 3.11, Django 5.2, and SQLite.

## System Architecture
- **Framework**: Django 5.2 (MVT Architecture)
- **Database**: SQLite with a relational inventory ledger
- **Security**: Role-Based Access Control (), PBKDF2 password hashing
- **Transactions**: Atomic updates () for inventory safety

## Product catalog (ORM)

Managers and Admins can open `/products/` from the POS **Products** link to search,
create, edit and safely delete products through Django ORM views. Stock stays
under receipt, sale and physical-count workflows. See [the ORM demo guide](docs/orm_catalog.md) for
presentation steps, implementation details and tests.

## Inventory adjustments and audit

Managers and Admins can open **Products → Adjust stock**, enter the physical
count and explain the difference. Posting saves the new balance and its audit
entry in one transaction. If another movement posts while the count is open,
reload the form and recount. Corrections use a new entry so the original
reason and balance remain visible.

Open **Products → Inventory audit → Download Excel** to review all recorded
sales, receipts and adjustments, including the user, time, product, source or
reason, and before/change/after quantities. The ledger starts with the first
posting after migration `0004_stock_movement`. Existing stock is the opening
balance. The ledger covers application posting workflows. Direct database
maintenance is outside its scope.

The [presentation workbook](outputs/01a20d0a-1c8c-7583-9cab-dcba88182c4a/inventory-audit-demo.xlsx)
reconciles a separate demo database. Five cartons received, three sold and one
damaged take an opening count of 20 to a closing count of 21.

## Team Roles
1. Systems Analysis & Requirements Lead: Aizada (24B031644)
2. Data & Database Lead: Kanat (24B032134)
3. Application & Development Lead: Nurali (24B031887)
4. Architecture & Security Lead: Ramazan (24B031964)
5. Testing, Analytics & Integration Lead: Adilet (24B032017)

## How to run on a new computer

Requirements: Python 3.11+ and git.

```bash
git clone <repository-url>
cd qoyma-erp

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # Windows: copy .env.example .env
```

Open `.env` and put your own random `SECRET_KEY` there. Generate one with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Then create the database and start the server:

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py test store -v 2
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with a demo user printed by `seed_demo`.

## Configuration (.env)

`SECRET_KEY` and `DEBUG` are read from environment variables, so they are not
stored in the repository. `python-dotenv` loads them from the `.env` file in the
project root; `.env` is listed in `.gitignore` and never committed, `.env.example`
is the template.

| Variable | Required | Meaning |
|----------|----------|---------|
| `SECRET_KEY` | yes | Django cryptographic key, unique per installation. The server refuses to start without it. |
| `DEBUG` | no (default `False`) | `True` (or `1`) only for local development. Keep `False` anywhere else. |

Variables can also be exported in the shell instead of `.env` — a real environment
variable takes priority over the file.

## Database backup and recovery

The database developer/steward maintains verified, full SQLite snapshots. Run:

```bash
python manage.py backup_db
python manage.py restore_db backup/<backup-filename>.sqlite3 --target backup/recovery-drill.sqlite3
python manage.py test store -v 2
```

Backups default to `backup/`; use `--output-dir` for another local directory.
Each backup has a unique UTC filename and passes SQLite integrity and foreign-key
checks. Recovery writes a new file and refuses to overwrite the live database.
Database files are ignored by Git.

See [backup operations and recovery runbook](backup/README.md) for scheduling,
retention, off-device storage, and the offline recovery procedure. Scheduling and
off-device copying are proposed operational steps, not automatically enabled.

## Automated tests

See the [QA guide](qa/README.md) for user stories, isolated unit tests, real
Chromium end-to-end tests, backup test provenance, execution results and open
defects. Browser tests require `requirements-test.txt` and the Chromium install
documented there; `python manage.py test store -v 2` runs the non-browser suite.

The testing lead owns the backup test suite and formal verification report.
The seven automated backup tests are in `store/test_backup.py`; run them with
`python manage.py test store.test_backup -v 2`. They use temporary databases.
See the backup runbook for the recovery drill and covered acceptance scenarios.

| ID | What is checked | Source |
|----|-----------------|--------|
| V-01 | Valid product is saved | Task 7 Data Dictionary |
| V-02 | Empty quantity is rejected | Task 7, Record 1 (Completeness) |
| V-03 | Negative price is rejected | Task 7, Record 2 (Validity) |
| V-04 | Duplicate barcode is rejected | Task 7, Records 3–4 (Uniqueness) |
| V-05 | Negative stock / non-13-digit barcode rejected | Task 7, Record 5 |
| AC-01 | Sale deducts stock, saves cashier, payment method and price snapshot | Main process |
| AC-02 | Selling more than in stock is refused, whole sale rolled back | Atomic transaction |
| AC-03 | Cashier gets 403 on alerts; Manager sees low-stock alert | RBAC |
| AC-04 | Anonymous user is redirected to login | Security |

## Stock receipt demo

Open `/admin/store/stockreceipt/add/`, select a supplier and receiving user,
then enter products, positive quantities and purchase prices. Click **Save**.
The admin saves the header and all lines and calls `StockReceipt.post()` inside
one database transaction. Stock increments use database `F()` expressions;
the calculated total and `posted` marker commit with the stock updates.
An error rolls back the entire receipt. Repeating `post()` does not add stock again.
Posted receipts are read-only in the admin and cannot be deleted there.

For scripts/imports, create the header and lines inside `transaction.atomic()`,
then call `receipt.post()` before leaving the transaction. A plain header `save()`
does not post anything because its inline items do not exist yet. Bulk ORM writes
and direct SQL bypass the admin workflow and must not edit posted documents.
The merge migration joins both receipt migration histories. It marks existing
receipts as posted without changing stock, preventing previously applied API
receipts from being applied twice. Historical receipts have no reliable posting
marker: reconcile any older, unprocessed admin receipts manually instead of
reposting them. New API/form receipts also set the marker in their stock-update
transaction. Back up the database before running `python manage.py migrate`.

Demo verified on 2026-11-10: receipt #1, Milk 2.5% 1L, 5 units at 400.00;
stock changed from 18.00 to 23.00, receipt total 2000.00.

Receipt tests cover admin saving, fractional quantities, totals, repeat posting,
read-only posted documents, invalid/empty receipts, cumulative receipts and rollback
after a stock update. Both API/form and admin receipt suites are preserved.
Run `python manage.py test store`; the separate browser suite is documented in
the QA guide.

### Barcode scanner for receipts

The admin receipt form includes a barcode field. Use a keyboard-mode USB/Bluetooth
scanner configured to send Enter after an EAN-13 barcode, or type a barcode and
press Enter. A known product is added with quantity 1; scanning it again adds 1.
Additional rows are created automatically. Enter purchase prices manually, then
click Save to post the complete receipt atomically. Scanning never updates stock.
Unknown codes and invalid input show a message without adding a line. The product
catalog is loaded when the form opens; newly created products become scannable
on a newly opened receipt form. The scanner field is hidden on posted receipts.


## Daily Sales Report

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)

The manager sees how the store performed today and can download the sales as CSV.

| URL | What it shows | Who can open |
|-----|---------------|--------------|
| `/report/` | Total sales, receipts, average receipt, split by payment method, top 5 products, low stock | Manager, Admin |
| `/report/csv/` | Today's sales as `sales_YYYY-MM-DD.csv` (one row per sold item) | Manager, Admin |
| Admin panel → **Reports** | Links to the report and CSV | Admin, staff |

Cashier gets **403 Forbidden** on both pages.

**Acceptance criteria:** `docs/daily_sales_report_criteria.md` (AC-D1…AC-D12)

**Code:**
- `store/reports.py` — `daily_sales_summary()` calculations
- `store/views.py` — `report_page`, `report_csv`
- `store/templates/store/report.html`, `store/templates/store/admin_index.html`

**Tests:**
```bash
python manage.py test store.test_daily_report store.test_report_page store.test_report_csv store.test_admin_report_link -v 2
```


## Documentation

- [User guide](docs/user_guide.md) — how cashier and manager use the system
- [UAT scenario and results](docs/uat_scenario.md) — 17-step acceptance test
- [UAT defects](docs/uat_defects.md) — defects found and their status

## Phone camera → receipt form on Mac

This feature is on the **admin StockReceipt form**, not the single-item `/receive/` page.
Install dependencies (`venv/bin/pip install -r requirements.txt`) and run
`venv/bin/python manage.py migrate` before starting the server.

1. Open `/admin/store/stockreceipt/add/` on Mac and click **Подключить телефон**.
2. Scan the pairing QR with the phone's normal camera. Open the link in Safari/Chrome
   and sign in as the **same staff user** with receipt and receipt-item add permissions.
3. Tap **Включить камеру** once and grant camera access (later visits start the camera
   automatically). Point at EAN-13 barcodes one after another — no buttons, no Enter.
4. On **Добавлено на Mac** the phone plays a "done" sound (a low tone on rejection) and the
   line appears in the Mac form (or its quantity increases by one). Scanning continues
   automatically. A barcode kept in view is counted once; to add another unit of the same
   product, move the camera away for ~1.5 s and back. A different product counts at once.
5. Enter purchase prices on Mac and save the receipt as usual. Scans only change
   the unsaved form. Existing atomic posting still handles inventory updates.

### HTTPS is required on the phone

`http://127.0.0.1:8002` works only on Mac. A phone camera requires a trusted HTTPS
origin; plain LAN HTTP and untrusted self-signed certificates are not sufficient.
Use an existing HTTPS reverse proxy / deployed site, or configure a locally trusted
certificate on both devices. For an existing HTTPS endpoint set in `.env`:

```dotenv
ALLOWED_HOSTS=127.0.0.1,localhost,erp.example.com
SCANNER_PUBLIC_BASE_URL=https://erp.example.com
CSRF_TRUSTED_ORIGINS=https://erp.example.com
```

Replace the example hostname with the real endpoint, proxy it to the Django server,
serve `/static/` normally, and restart Django. The public base URL must point to
**this same application and database**, without a path prefix. Keep Mac and phone
on the same HTTPS origin where possible. Configure forwarded-protocol trust only
for a trusted reverse proxy that strips client-supplied forwarded headers.
No tunnel or public exposure is enabled automatically by this change.

### Reliability and access

Each open form gets a random session UUID valid for 30 minutes. All endpoints require
login, ownership and receipt permissions; write requests require CSRF. The phone
link alone does not grant access. Mac polls the queue once per second and acknowledges
whether the scan was added or rejected. Retries retain the same request UUID; a unique
DB constraint prevents duplicate events, and Mac caches already handled events until
the pairing closes. Repeated deliberate scans get new UUIDs and add one each.

Keep the Mac tab open and active. After 20 seconds without its heartbeat, new scans
are refused until Mac reconnects. Navigating away, saving the form, or clicking
**Отключить телефон** closes the pairing; expired sessions are rejected server-side.
Reloading the page does not restore unsaved receipt rows: reconnect the phone and
check the form before continuing. Unknown codes do not create products automatically.
The catalog is loaded when the Mac form opens; newly created products require a new form.
Camera frames stay on the phone; only the barcode and request UUID go to the server.

ZXing Browser 0.1.5 is vendored under `store/static/store/vendor/` with its license,
so camera decoding does not depend on a runtime CDN request. QR generation uses
`qrcode==8.2`. The manual code field on the phone page is a fallback and permits
relay testing without camera hardware. It does not substitute for a real-device
camera test on iOS/Android over HTTPS.

Tests: `venv/bin/python manage.py test store.test_phone_scanner`.

### Local Wi-Fi camera demo (no public hosting)

The repository includes `setup_scanner_tls` and `runscanner_tls` for local development.
They generate certificates under the ignored `.scanner-tls/` folder. They do **not**
install a CA into system trust. Only distribute `.scanner-tls/public/qoyma-local-ca.cer`;
never distribute `ca.key` or `server.key`.

1. Find the Mac Wi-Fi IPv4 address (`ifconfig en0`) and replace `<LAN-IP>` below.
2. Generate a 30-day server certificate: `venv/bin/python manage.py setup_scanner_tls --host <LAN-IP>`.
3. Set `.env`: `ALLOWED_HOSTS=127.0.0.1,localhost,<LAN-IP>`,
   `SCANNER_PUBLIC_BASE_URL=https://<LAN-IP>:8443`,
   `CSRF_TRUSTED_ORIGINS=https://<LAN-IP>:8443`.
4. Start HTTPS: `venv/bin/python manage.py runscanner_tls <LAN-IP>:8443 --noreload`.
5. In another terminal start the Mac-only UI:
   `venv/bin/python manage.py runserver 127.0.0.1:8004 --noreload`.
6. Transfer the **public** CA to your phone (AirDrop is fine), or temporarily serve
   only that folder: `venv/bin/python -m http.server 8765 --bind <LAN-IP> --directory .scanner-tls/public`.
   Download `http://<LAN-IP>:8765/qoyma-local-ca.cer` on the phone.
7. Install and trust the CA on your own phone. On iPhone install the downloaded
   profile in Settings → General → VPN & Device Management, then enable it under
   General → About → Certificate Trust Settings. On Android use Security →
   Encryption & credentials → Install a certificate → CA certificate (labels vary).
   This explicitly trusts certificates signed by this local CA; remove the profile
   after the demo if no longer needed. Do not bypass browser certificate warnings.
8. Both devices must share a Wi-Fi network allowing peer-to-peer connections. Open
   `http://127.0.0.1:8004/admin/store/stockreceipt/add/` on Mac, click Connect Phone,
   scan its QR on the phone, sign in with the same user and allow the camera.

If the Mac IP changes, regenerate the server certificate with the new IP, update
`.env`, and restart both servers. The CA remains the same. Stop the certificate
HTTP server after transferring the CA. The development HTTPS command is not a
production deployment server. Camera permission and certificate trust on the physical
phone must be completed by its owner.
