# User Acceptance Test (UAT) — Qoyma ERP

Owner: Aizada Amanova (Systems Analysis & Requirements Lead)

Goal: check that the main store process works from start to finish
before the Week 15 defence.

Preparation: `python manage.py seed_demo` → `python manage.py runserver`
→ open http://127.0.0.1:8000/login/

## Scenario

| # | Role | Action | Expected result | Result |
|---|------|--------|-----------------|--------|
| 1 | Cashier | Log in as cashier / QoymaCashier2026 | POS screen opens, 33 products in stock table | |
| 2 | Cashier | Add Milk (4870000000011) qty 2, pay Cash, Complete sale | "Sale completed", Milk stock 20 → 18 | |
| 3 | Cashier | Add Kefir (4870000000028) qty 10, Complete sale | Error "Insufficient stock", Kefir stays 4 | |
| 4 | Cashier | Type unknown barcode 1234567890123 | Error "Product not found" | |
| 5 | Cashier | Open /receive/ | 403 Forbidden | |
| 6 | Cashier | Open /report/ | 403 Forbidden | |
| 7 | Cashier | Log out | Login page opens | |
| 8 | Manager | Log in as manager / QoymaManager2026 | POS screen with Receive stock, Daily report, Admin links | |
| 9 | Manager | Receive stock: Milk qty 50, valid expiry date | "Stock: 18 → 68" | |
| 10 | Manager | Receive stock: qty -5 | Error, stock unchanged | |
| 11 | Manager | Receive stock: expiry date = yesterday | Error "already expired", stock unchanged | |
| 12 | Manager | Open Daily report | Total 1 100 ₸, 1 receipt, Cash 1 100 ₸, Milk in top products | |
| 13 | Manager | Click Download CSV | sales_YYYY-MM-DD.csv downloads, opens in Excel, 1 row (Milk) | |
| 14 | Manager | Admin → Products → Add, price -190 | Red error, product not saved | |
| 15 | Admin | Log in as admin / QoymaAdmin2026, open /admin/ | Reports block with Daily sales report link | |
| 16 | Manager | Open /products/ | Product list opens with 33 products | |
| 17 | Manager | /products/new/ → add product with price -190 | Error, product not saved | |

## Summary

| Total steps | Pass | Fail |
|-------------|------|------|
| 17 | | |