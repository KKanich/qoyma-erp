# Stress Test Report — `stress-test` Branch

## Provenance

- Branch: `stress-test` created from `orm` (`e98fb947246a25447970e7732da3b005d7ef7ce4`).
- Test module: [`store/test_stress.py`](../store/test_stress.py).
- Production application code was not modified on this branch.

## Execution Summary

Executed in the local Python 3.11 virtual environment (`./venv/bin/python`) with a test-only `SECRET_KEY`:

| Command | Discovered | Passed | Expected Failures | Unexpected Failures/Errors | Duration |
|---|---:|---:|---:|---:|---:|
| `python manage.py check` | — | 0 issues | — | 0 | — |
| `python manage.py test store.test_stress -v 2` | 15 | 15 | 0 | 0 | 11.867 s |
| `python manage.py test store -v 2` | 80 | 78 | 2 | 0 | 23.089 s |

The two expected failures in `store` (`test_d01_json_array_should_return_400_not_500`, `test_d02_nan_quantity_should_return_400_not_500` in [`store/test_qa.py`](../store/test_qa.py)) correspond to open defects `QA-01` and `QA-02` documented in [`qa/DEFECTS.md`](../qa/DEFECTS.md).

## 1. Parameter Stress Matrix (`ParameterStressTests`)

- **Catalog list (`GET /products/`, `store.catalog.product_list`)**:
  - `q`: empty, whitespace-only, exact/case-insensitive name, full/partial 13-digit barcode, Kazakh Cyrillic (`Құрт`, `Құр`), SQL/HTML characters (`"'<>%;--`, `<script>alert(1)</script>` verified escaped), 500-char string, non-matching term.
  - `low`: `''`, `'1'`, `'0'`, `'true'`, `'2'`, `'-1'`, `'yes'`.
  - `page`: `''`, `'1'`, `'2'`, `'0'`, `'-1'`, `'999999'`, `'abc'`.
- **Catalog create & edit (`GET/POST /products/new/`, `/products/<pk>/edit/`, `ProductForm`, `store.catalog.product_edit`)**:
  - `barcode`: `'0000000000000'`, `'9999999999999'`; invalid 12-digit, 14-digit, alphanumeric, whitespace-containing, negative, empty, and duplicate values on both create and edit.
  - `name`: 1-char, 200-char boundary, 201-char overflow, empty/whitespace, Kazakh Unicode + HTML payload (`<b>Сүт & Honey</b>` verified escaped in list rendering).
  - `category` / `supplier`: valid PKs, optional blank supplier (`SET_NULL`), missing PK (`999999`), empty, non-numeric.
  - `sale_price` & `min_quantity`: lower/upper `Decimal(10, 2)` boundaries (`0.01`/`0.00` to `99999999.99`), zero/negative, 11-digit overflow, 3-decimal precision, non-numeric, `NaN`, `Infinity`, `-Infinity`, empty.
  - `expiry_date`: past (`2020-01-01`), leap day (`2028-02-29`), far future (`2099-12-31`), invalid (`2026-02-30`, `not-a-date`), empty.
  - `quantity` injection on create/edit (always initialized to `0.00` on create and preserved via `update_fields` on edit), 404 on missing `pk`, 405 on unsupported HTTP methods (`POST` on list, `PUT`/`DELETE`/`PATCH` on list/edit/delete).
- **Catalog delete (`GET/POST /products/<pk>/delete/`, `store.catalog.product_delete`)**:
  - 404 on missing `pk`; `GET` renders confirmation without deleting; `POST` blocks stocked products, zero-stock products referenced by `SaleItem` (`RESTRICT`), and zero-stock products referenced by `StockReceiptItem` (`RESTRICT`); deletes unreferenced zero-stock products.
- **Stock receipt (`receive_stock`, `POST /api/stock-receipt/`, `GET/POST /receive/`)**:
  - Role check (`PermissionDenied` for Cashier), empty items list, whitespace-padded barcodes, `0.01` minimum and `999999.99` × `9999.99` high boundaries, `today` vs `today - 1 day` expiry, zero/negative/non-numeric/`None` quantities and purchase prices, missing/invalid `supplier_id`, malformed JSON (`400`), `GET` (`405`), and HTML form errors on `/receive/`.
- **POS checkout (`POST /api/checkout/`, `store.views.pos_checkout`)**:
  - `GET` (`405`), malformed JSON (`400`), all valid payment methods (`Cash`, `Kaspi_QR`, `Card`), invalid payment methods (`''`, `'Kaspi'`, `'Crypto'`, `None`), `0.01` fractional quantity, exact remaining stock vs `+0.01` oversell rollback, `0`/negative/non-numeric/`None` quantities, whitespace-padded and unknown barcodes.
- **Alerts, reports, RBAC & CSRF (`dashboard_alerts`, `daily_sales_summary`, `/report/`, `/report/csv/`)**:
  - Expiry boundary (`-1`, `0`, `+7` days included; `+8` days excluded), low-stock boundary (`<= min_quantity` included; `> min_quantity` excluded), date-filtered summaries (`today`, `yesterday`, future empty day), top-5 product ordering (`-qty`, `product__name`), anonymous redirects (`302`), Cashier RBAC (`403`), Manager/Admin access (`200`), and `Client(enforce_csrf_checks=True)` (`403` without token across all mutating endpoints).

## 2. Repository ORM Functions Verified (`AllORMFunctionsStressTests`)

- `store.management.commands.seed_demo`: idempotency across repeated `call_command('seed_demo')` runs (`3` users, `8` categories, `2` suppliers, `33` products, `17` store permissions assigned to `manager`).
- `Category.__str__`, `Supplier.__str__`, `Product.__str__`, `barcode_validator`, `Product.save()` (`self.full_clean()` enforcement on direct ORM updates with `update_fields`).
- Relational `on_delete` constraints across all 8 models:
  - `RESTRICT`: `Category -> Product`, `Supplier -> StockReceipt`, `User -> Sale`, `User -> StockReceipt`, `Product -> SaleItem`, `Product -> StockReceiptItem`.
  - `SET_NULL`: `Supplier -> Product` (when no `StockReceipt` references the supplier).
  - `CASCADE`: `Sale -> SaleItem`, `StockReceipt -> StockReceiptItem`.
- `StockReceipt.post()`: unsaved (`pk=None`) `ValidationError`, empty-items `ValidationError`, `total_amount` `max_digits=12` overflow rollback of `F('quantity') + item.quantity` and `posted=True`, and single-application posting with `quantize(Decimal('0.01'))`.
- QuerySet & aggregation APIs: `select_related('category', 'supplier')`, `select_for_update()`, `filter(Q(...) | Q(...))`, `filter(quantity__lte=F('min_quantity'))`, `aggregate(Sum(...))`, `values(...).annotate(Sum(...))`, `Paginator.get_page(...)`, and constant `4`-query verification (`assertNumQueries(4)`) on `product_list`.

## 3. Server Load & Concurrency Tests (`ServerLoadStressTests`, `LiveServerLoadStressTests`)

- **High-volume workload (`ServerLoadStressTests.test_high_volume_catalog_receipt_checkout_report_and_backup_load`)**:
  - Created `250` products (`25` via `POST /products/new/`, `225` via ORM), edited `50` via `POST /products/<pk>/edit/`, deleted `30` unused zero-stock products via `POST /products/<pk>/delete/`, leaving `220` active products.
  - Paginated across all `9` pages of `/products/` verifying `4` SQL queries per page.
  - Executed `100` stock receipts (`40` multi-line via `/api/stock-receipt/`, `20` via `/receive/`, `20` via `receive_stock()`, `20` via `StockReceiptAdmin`), verifying `posted=True` on all `100` receipts.
  - Executed `150` two-line POS checkouts (`300` `SaleItem` rows) across `Cash`, `Kaspi_QR`, and `Card`.
  - Verified exact per-product stock conservation across all `220` products, exact revenue reconciliation across `Sale.objects.aggregate(Sum('total_amount'))`, `daily_sales_summary()`, `/report/`, and `/report/csv/` (`301` CSV rows), and full `backup_db` / `restore_db` round-trip verification (`220` products, `150` sales, `300` sale items) from an `iterdump()`-materialized SQLite snapshot.
- **Live WSGI HTTP server load & concurrency (`LiveServerLoadStressTests`)**:
  - Authenticated via live `/login/` form + CSRF token, created a product via live HTTP `POST /products/new/`, executed `80` TCP/HTTP `GET` requests across `/`, `/products/`, `/products/?page=2`, `/products/?q=Live&low=1`, `/api/alerts/`, `/report/`, `/report/csv/`, and `/receive/`, and executed `20` live HTTP CSRF-protected `POST /api/checkout/` sales.
  - Executed `4` synchronized worker threads racing on `StockReceipt.post()`, verifying the conditional `.filter(pk=self.pk, posted=False).update(posted=True)` guard applies stock exactly once (`1` `True`, `3` `False`).

## 4. Observations & Known Edge Cases

- In `store/services.py` (`receive_stock`), `receipt.total_amount` is assigned `total` without `.quantize(Decimal('0.01'))` before `receipt.save()`, so an unrefreshed instance may hold extra decimal places in memory until `refresh_from_db()` reads the 2-decimal DB value (unlike `StockReceipt.post()`, which explicitly quantizes `total`).
- As previously documented in [`qa/DEFECTS.md`](../qa/DEFECTS.md) (`QA-01`, `QA-02`), `pos_checkout` and `stock_receipt_api` do not normalize non-object JSON payloads (such as `[]`) or non-finite decimals (`NaN`) before dictionary/comparison operations.
- Under Django's default `:memory:` SQLite test configuration, `LiveServerTestCase` shares one `sqlite3` connection across WSGI threads via `connections_override`; concurrent HTTP requests against `:memory:` SQLite contend on that shared connection, whereas sequential HTTP requests over TCP/WSGI and separate-thread `StockReceipt.post()` calls with thread-local connections execute reliably.
