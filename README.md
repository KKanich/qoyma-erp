# Qoyma ERP - Grocery Store Management System

Qoyma is a lightweight, offline-capable ERP system designed for small grocery stores (such as «Bereke» in Almaty). Built with Python 3.11, Django 5.2, and SQLite.

## System Architecture
- **Framework**: Django 5.2 (MVT Architecture)
- **Database**: SQLite3 () with relational 8-entity schema
- **Security**: Role-Based Access Control (), PBKDF2 password hashing
- **Transactions**: Atomic updates () for inventory safety

## Team Roles
1. Systems Analysis & Requirements Lead: Aizada (24B031644)
2. Data & Database Lead: Kanat (24B032134)
3. Application & Development Lead: Nurali (24B031887)
4. Architecture & Security Lead: Ramazan (24B031964)
5. Testing, Analytics & Integration Lead: Adilet (24B032017)

## How to run

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations store
python manage.py migrate
python manage.py seed_demo
python manage.py test store -v 2
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in with a demo user printed by `seed_demo`.

## Automated tests

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
Existing receipts are not automatically applied by the migration.

Demo verified on 2026-11-10: receipt #1, Milk 2.5% 1L, 5 units at 400.00;
stock changed from 18.00 to 23.00, receipt total 2000.00.

Receipt tests cover admin saving, fractional quantities, totals, repeat posting,
read-only posted documents, invalid/empty receipts, cumulative receipts and rollback
after a stock update. Run `python manage.py test store` (14 tests).
