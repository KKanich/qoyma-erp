# User Acceptance Test (UAT) — Qoyma ERP

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)

Goal: check that the main store process works from start to finish
before the Week 15 defence.

Preparation: `python manage.py seed_demo` → `python manage.py runserver`
→ open http://127.0.0.1:8000/login/

Run date: 17 November 2026 · Tester: Aizada Amanova

## Scenario

| # | Role | Action | Expected result | Result |
|---|------|--------|-----------------|--------|
| 1 | Cashier | Log in as cashier / QoymaCashier2026 | POS screen opens, 33 products in stock table | Pass |
| 2 | Cashier | Add Milk (4870000000011) qty 2, pay Cash, Complete sale | "Sale completed", Milk stock 20 → 18 | Pass |
| 3 | Cashier | Add Kefir (4870000000028) qty 10, Complete sale | Error "Insufficient stock", Kefir stays 4 | Pass |
| 4 | Cashier | Type unknown barcode 1234567890123 | Error "Product not found" | Pass |
| 5 | Cashier | Open /receive/ | 403 Forbidden | Pass (see D-04) |
| 6 | Cashier | Open /report/ | 403 Forbidden | Pass (see D-04) |
| 7 | Cashier | Log out | Login page opens | Pass |
| 8 | Manager | Log in as manager / QoymaManager2026 | POS screen with Receive stock, Daily report, Admin links | Pass |
| 9 | Manager | Receive stock: Milk qty 50, valid expiry date | "Stock: 18 → 68" | Pass |
| 10 | Manager | Receive stock: qty -5 | Error, stock unchanged | Pass |
| 11 | Manager | Receive stock: expiry date = yesterday | Error "already expired", stock unchanged | Pass |
| 12 | Manager | Open Daily report | Total 1 100 ₸, 1 receipt, Cash 1 100 ₸, Milk in top products | Pass (see D-02) |
| 13 | Manager | Click Download CSV | File opens in Excel with data in separate columns | Pass after fix (Download Excel, D-01 fixed); |
| 14 | Manager | Admin → Products → Add, price -10 | Red error, product not saved | Pass |
| 15 | Admin | Log in as admin / QoymaAdmin2026, open /admin/ | Reports block with Daily sales report link | Pass (see D-03) |
| 16 | Manager | Open /products/ | Product list opens with 33 products | Pass |
| 17 | Manager | /products/new/ → add product with price -50 | Error, product not saved | Pass |

## Summary

| Total steps | Pass | Fail |
|-------------|------|------|
|     17      |  17  |   0  |

The main process (sale → stock receipt → report) works from start to finish.
Defects found: see `docs/uat_defects.md`.