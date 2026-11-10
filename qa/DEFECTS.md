# Open QA defects

Observed 2026-11-10. These are application defects exposed by the new integration
tests. The QA branch records them without changing application behavior.

## QA-01 — Checkout assumes the JSON body is an object

- Severity: medium; authenticated malformed requests cause a server error.
- Story: US-03. Reproduction: log in, then POST `[]` as `application/json` to
  `/api/checkout/` with a valid CSRF token (the integration client supplies an
  authenticated request with its normal test CSRF bypass).
- Expected: HTTP 400 with a clear invalid-request error.
- Actual: HTTP 500; `pos_checkout` calls `.get()` on a list.
- Regression: `store.test_qa.QAIntegrationTests.test_d01_json_array_should_return_400_not_500`.
- Suggested fix for application developer: validate the top-level object, items
  list and each item object before reading fields. Add cases for `null`, numbers,
  strings and non-object items, then remove the expected-failure annotation.

## QA-02 — Non-finite checkout quantities are not rejected cleanly

- Severity: medium; authenticated malformed quantities cause a server error.
- Story: US-03. Reproduction: with a valid product barcode, POST
  `{"items":[{"barcode":"4870000000011","qty":"NaN"}]}` to `/api/checkout/`.
- Expected: HTTP 400 and no sale or stock update.
- Actual: HTTP 500; `Decimal('NaN')` parses but raises `InvalidOperation` when
  compared with zero outside the parsing exception handler.
- Regression: `store.test_qa.QAIntegrationTests.test_d02_nan_quantity_should_return_400_not_500`.
- Suggested fix for application developer: reject non-finite decimals before
  comparison; review the same pattern in stock receipt quantities/prices. Add
  infinity and decimal-precision cases, then remove the annotation.

## Triage and retest

The Testing/QA lead reports reproduction and expected behavior to the application
developer. The developer implements a fix; QA removes `expectedFailure`, reruns
the full integration suite and relevant browser journeys, and records the fix
commit plus results. These cases are not waived requirements or passing tests.
