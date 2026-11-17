# Product catalog through Django ORM

ORM means **Object-Relational Mapping**. This feature exposes existing Product,
Category and Supplier models through manager-facing Django views.

## Run and demonstrate

Follow the README setup, migrations and demo seeding on a demo database. Start
`python manage.py runserver`, sign in as a Manager or Admin, then click **Products**
in the POS navigation or open `/products/`.

1. Search for an existing name or barcode; enable **Low stock only**.
2. Create a product with a unique 13-digit barcode, a category, a positive price
   and a valid expiry date. Stock starts at zero.
3. Edit its name or price, save, and refresh to show persistence.
4. Submit an invalid price or duplicate barcode to show field validation.
5. Delete an unused zero-stock product through the confirmation page.
6. Try deleting a stocked or historical product: the record remains intact.
7. Sign in as a Cashier: catalog access returns 403.

Categories and suppliers are maintained in the existing Django admin. Inventory
changes use the existing Receive stock and POS workflows. No Excel integration
or schema migration is needed for this feature.

## Request-to-data flow

| Operation | URL | ORM behavior |
|---|---|---|
| Read/search | GET `/products/` | `filter(Q(...))`, `F()` low-stock comparison, `select_related()` joins, pagination |
| Create | GET/POST `/products/new/` | `ModelForm` validation, `Product.save()` with zero initial stock |
| Update | GET/POST `/products/<id>/edit/` | fetch existing object, validate, save only catalog fields |
| Delete | GET/POST `/products/<id>/delete/` | GET confirms; POST checks zero stock and deletes; relational restrictions preserve history |

`store/catalog.py` implements the views; `store/forms.py` defines editable fields.
Templates render validation errors and escaped values. Mutations require POST,
CSRF protection and the existing role decorator. Successful writes redirect to
avoid accidental resubmission. Database integrity errors are handled outside a
nested atomic block so the enclosing transaction remains usable.

`select_related('category', 'supplier')` avoids a query for every related table
cell. Edits use `update_fields` to avoid overwriting inventory quantities changed
by other workflows. SQLite does not provide row locks for `select_for_update`;
the application retains SQLite's concurrency limitations. This feature does not
claim to fix concurrency in the existing checkout workflow.

## Verification

```bash
python manage.py test store.test_catalog -v 2
python manage.py test store -v 1
python manage.py check
```

Tests cover CRUD persistence, stock preservation, invalid and duplicate data,
search and stock filters, protected deletion, roles, CSRF, missing records and
constant query count for related records.
