# QA execution report — 2026-11-10

Work performed during the week of 2026-11-09 through 2026-11-15. This report
records work executed on November 10; it does not imply activity on other days.

## Baseline and contribution

- Implementation baseline: merge `cd22979`, including backup implementation
  `89e513a` and the configuration changes on `main`.
- Existing supplied-test baseline: `87b1ebe` on `tests`; `testing` was created
  from it after fetching origin.
- Existing coverage: 14 application acceptance tests and 7 supplied backup tests.
- New QA work: 8 isolated unit tests, 4 additional integration tests, 2 explicit
  regression cases for open defects, and 3 real browser journeys; user-story
  traceability, a defect register, reproducible setup and a CI workflow.
- The supplied backup tests matched the developer ZIP after normalizing line
  endings. Archive checksum and source attribution are in the QA README.

## Environment

Windows, Python 3.12.6, Django 5.2.19, SQLite 3.45.3, Playwright 1.65.0, installed
Google Chrome 156.0.8078.80 in headless mode. A process-only test `SECRET_KEY` was
used. Django created and destroyed a test database; backup checks used temporary
SQLite files. Browser cases logged in through forms using synthetic accounts.

## Executed commands and outcomes

With the local virtual environment activated:

```powershell
$env:SECRET_KEY = 'temporary-qa-test-key-not-for-deployment'
python manage.py test store -v 2
$env:QA_BROWSER_CHANNEL = 'chrome'
python manage.py test qa.test_browser -v 2
```

| Execution | Discovered | Passed | Expected failures | Unexpected failures/errors | Runner duration |
|---|---:|---:|---:|---:|---:|
| Non-browser suite (`store`) | 35 | 33 | 2 | 0 | 11.448 seconds |
| Browser suite (`qa.test_browser`) | 3 | 3 | 0 | 0 | 13.928 seconds |
| Total | 38 | 36 | 2 | 0 | Separate runs |

Django system checks found no issues in either run. `git diff --check` also
passed. Counts refer to test methods; parameterized subcases are not counted as
separate tests. The backup suite's seven tests are included in the 33 non-browser
passes. No percentage coverage claim is made.

## Findings and acceptance decision

US-01, US-02 and US-04–US-07 have passing evidence for the scoped criteria in the
traceability matrix. US-03 is only partially accepted: QA-01 (array JSON body)
and QA-02 (`NaN` quantity) return HTTP 500 instead of a validation response.
These cases are marked `expectedFailure` and remain open in `DEFECTS.md`.
The runner's `OK (expected failures=2)` must not be described as all tests passed.

The browser check covered receive-to-sale persistence, rejected overselling,
bad credentials, cashier authorization and logout. Recovery testing proved a
temporary database could recover deleted rows. No live recovery cutover, remote
copy, load test, or timed 30-minute recovery objective was verified.

## CI status

A workflow is supplied for Python 3.11 / Linux / Playwright Chromium. Local
Windows/Chrome outcomes do not certify that environment. Check the GitHub Actions
run after push; its result is not asserted in this local execution report.

## Follow-up

Application developer: fix QA-01 and QA-02 and expand payload-shape/numeric input
validation. QA: remove expected-failure markers after fixes, rerun affected
integration and browser scenarios, and record actual results and fix commits.
Database steward: execute and time the operational restore drill separately.
