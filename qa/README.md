# QA verification

This branch adds testable [user stories](USER_STORIES.md), isolated unit checks,
additional integration coverage and real Chromium end-to-end journeys. Test data
is created in Django's test database or temporary SQLite files; the local
application database is not used as test data.

## Setup and execution

With the project virtual environment activated:

```bash
python -m pip install -r requirements-test.txt
python -m playwright install chromium
```

Configure `SECRET_KEY` using the project's `.env.example`, or supply a test-only
value in the process environment. Never use the test key for a deployment.

PowerShell example:

```powershell
$env:SECRET_KEY = 'temporary-qa-only-key-not-for-deployment'
python manage.py test store.test_unit -v 2
python manage.py test store -v 2
python manage.py test qa.test_browser -v 2
```

POSIX shells can use `export SECRET_KEY='temporary-qa-only-key-not-for-deployment'`.
No separate `runserver`, real accounts, or demo seed command is needed. The live
test server uses an available local port. For a visible browser demonstration,
set `QA_HEADED=1` in the process environment before running browser tests.
If Chrome is already installed, setting `QA_BROWSER_CHANNEL=chrome` uses it
instead of downloading Playwright's Chromium. Leave the variable unset to use
the installed Playwright browser, as CI does.

`.github/workflows/qa.yml` runs the combined suite on pushes to `main`, `tests`
and `testing`, and on pull requests, using Python 3.11 on Linux. The workflow
installs Chromium's OS dependencies. Its actual remote result must be checked in
GitHub Actions; a local run does not establish that the CI job passed. Known
expected failures are still open defects even when the job succeeds.

## What each layer proves

| Layer | Source | Scope |
|---|---|---|
| Unit | `store/test_unit.py` | 8 tests of field validators, role guards and service preconditions. `SimpleTestCase` forbids database access. A mocked view checks that denied roles cannot invoke it. |
| Integration | `store/tests.py`, `store/test_qa.py` | Existing 14 acceptance tests, 4 additional transaction/HTTP tests, and 2 expected-failure regression cases. Uses real Django models, middleware and a temporary test database. |
| Backup integration | `store/test_backup.py` | 7 supplied tests exercise actual SQLite files and management commands. These are integration checks, not pure unit tests. |
| Browser E2E | `qa/test_browser.py` | 3 Chromium journeys exercise rendered forms, login, CSRF, JavaScript cart/checkout, HTTP server, persistence, access denial and logout. No business API responses are mocked. |

E01 follows manager receipt → logout → cashier login → sale → persisted stock →
logout. E02 verifies overselling fails without a sale. E03 verifies bad login and
cashier denial at the direct receive URL. Each scenario gets fresh users and
stock. Playwright is stopped before synchronous ORM assertions, preserving
Django's async-safety checks. Browser tests use [Playwright's Python library](https://playwright.dev/python/docs/library)
and Django's [live-server testing support](https://docs.djangoproject.com/en/5.2/topics/testing/tools/#liveservertestcase).

## Backup contribution and provenance

The database developer supplied `qoyma-backup-testing-handoff.zip`. QA compared
its `store/test_backup.py` with the tracked test file: they match after line-ending
normalization. The archive SHA-256 is:

```text
e43502286e3594f90b9b4ac1ddde7b3a9dcbca4c137df714b4535d2d75013c3f
```

Git history establishes the implementation at `89e513a` on `backup`, its merge to
`main` at `cd22979`, and the supplied test addition at `87b1ebe` on `tests`.
At the QA fetch on 2026-11-10, `origin/main` already included the backup merge and
`origin/tests` included the tests. `testing` starts from that test commit.
The QA contribution here is integration, review, additional coverage and results;
the supplied backup tests are not claimed as newly authored QA code. The archive
is a handoff artifact and is not required to run the checked-in tests.

## Results and limits

See [the dated execution report](REPORT.md) for measured outcomes and
[the defect register](DEFECTS.md) for the two known checkout failures. The
`expectedFailure` annotations make these failures explicit; remove them when
fixes land. An unexpected success fails the suite, prompting that review.

Coverage does not establish production readiness. This work does not measure
percentage coverage, performance under concurrent cashiers, cross-browser/mobile
behavior, accessibility, remote backup storage, a timed disaster recovery RTO,
or security beyond the specific authorization/CSRF scenarios. Visual browser
automation does not replace a human usability review.
