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
