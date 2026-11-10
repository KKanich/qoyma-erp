# QA user stories and acceptance traceability

Prepared for the Tester / QA role on 2026-11-10. These stories clarify testable
behavior of the existing application; they do not replace the requirements
lead's original acceptance criteria. IDs below map to executable test names.

| Story | User need | Given / When / Then acceptance criteria | Evidence |
|---|---|---|---|
| US-01 Staff login | As a staff member, I want to sign in and sign out so only authorized staff use the ERP. | Given valid staff credentials, when I submit login, then POS opens. Given an incorrect password, then an error appears. After logout, visiting POS redirects to login. | Browser E01/E03; unit U04 |
| US-02 Cashier sale | As a cashier, I want to sell available stock and choose payment so the receipt and inventory agree. | Given 25 units at 550, when I sell 2 by Card, then total is 1100, stock is 23, and the payment method and item price are saved. A later catalog price change must not alter the recorded sale. | Browser E01; integration I04; existing AC-01 |
| US-03 Safe checkout | As a cashier, I want an invalid sale rejected without partial stock changes. | Given stock of 20, when I request 21, then the UI reports insufficient stock and saves no sale. Empty carts, unknown barcodes, nonpositive quantities and unsupported payments return 400. Malformed JSON shapes and non-finite quantities should also return 400. | Browser E02; I02; existing AC-02; D01/D02 (open defects) |
| US-04 Receive stock | As a manager, I want to receive valid supplier deliveries so inventory and purchase totals are accurate. | Given 20 units, when I receive 5 at 400, then stock becomes 25 and receipt total is 2000. If a later item is invalid, all receipt items and stock changes roll back. Expired deliveries are rejected. | Browser E01; I01; existing AC-R1/R2/R4; U08 |
| US-05 Role and request protection | As a manager, I want privileged actions restricted so cashiers cannot change incoming stock. | A cashier sees no Receive stock link and receives 403 on direct access. Manager/Admin roles pass the role guard. A checkout POST without a CSRF token receives 403 and saves no sale. | Browser E03; U04–U07; I03; existing AC-R3 |
| US-06 Product quality | As a data steward, I want invalid product data rejected before saving. | Barcodes must have 13 digits, price must be at least 0.01, and stock must be nonnegative. Duplicate barcodes and missing quantities are rejected by model validation. | U01–U03; existing V-01–V-05 |
| US-07 Recovery | As a database steward, I want verified snapshots and a safe recovery drill so lost records can be recovered without overwriting live data. | A snapshot restores earlier rows after deletion; committed WAL changes are included and uncommitted changes excluded. Existing/live targets, invalid sources and broken foreign keys are rejected. Failures leave no published partial file. | Seven supplied backup tests in `store/test_backup.py` |

## Completion criteria

Run the isolated unit suite, database/integration suite and real browser journeys.
Record versions, date, commands and outcomes. An expected failure is an open
defect, not a passed requirement. The QA-01/QA-02 issues must be fixed and their
regression tests pass normally before claiming full US-03 acceptance. Production
readiness also requires the untested areas listed in the QA README.
