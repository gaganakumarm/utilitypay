# UtilityPay fix verification report

Date: 2026-09-07

## Result

**All 58 automated tests pass: 0 failed, 0 skipped.** The previous run had 8 failing tests covering 6 issues; those regressions now pass. Fourteen additional cases cover the fixes and their recovery paths.

| Check | Result |
|---|---|
| Full suite on Windows Python 3.12.7 against real PostgreSQL 16 | 58 passed in 51.46 seconds |
| Full suite inside the Linux application container | 58 passed in 13.21 seconds |
| Application statement/branch coverage, excluding test files | 93% |
| Django system check | No issues |
| Migration/model consistency | No changes detected |
| New database constraint migration | Applied in Docker |
| Live HTTP, scheduled Celery flow, audit history, timeout persistence | Passed; smoke script exited 0 |
| Deployment configuration check | 7 development-configuration warnings remain |

## Fixes verified

1. **Audit API:** corrected EventSerializer's read-only field configuration. Authenticated list and detail requests now return 200.
2. **Payment integrity:** API updates reject changes to the bill, amount, provider reference, or provider status of a reconciled payment. Unchanged updates remain valid. Update transactions acquire row locks before validation to serialize updates with reconciliation.
3. **Missing payment:** reconciliation uses the viewset object lookup and handles a deletion between lookup and reconciliation, returning 404.
4. **Timeout diagnostics:** the service saves the error inside a transaction and raises TimeoutError after that transaction exits. The error is preserved for API/worker callers and clears after a subsequent non-timeout provider response. As with other database writes, an enclosing caller transaction could still roll it back.
5. **Duplicate events:** audit events are written only when reconciliation status changes. Repeated FAILED or MANUAL_REVIEW outcomes do not duplicate events. Corrected payments can still transition to RECONCILED and produce a new event.
6. **Bill amounts:** API validation rejects zero and negative values on creation and update. Migration 0002 adds a PostgreSQL check constraint so direct database writes cannot bypass this rule.

## Test coverage

Tests cover authentication, JWT refresh and invalid tokens, CRUD, invalid payment inputs, immutable reconciliation fields, filtering, all provider outcomes, timeout recovery, corrected failed/manual-review payments, audit list/detail, repeated reconciliation, task selection, eager retry exhaustion, database constraints, atomic rollback, and two simultaneous PostgreSQL reconciliation threads.

The live smoke script exercises Gunicorn HTTP, JWT login, record creation, Celery Beat scheduling, Redis dispatch, worker reconciliation, paid bill status, repeated reconciliation with one readable audit event, and a TIMEOUT response whose diagnostic survives HTTP 503.

Services, serializers, tasks, and views report 100% coverage in the local coverage run. Overall application coverage is 93%; seed-command and WSGI startup execute in Docker outside that measurement. Coverage is not a guarantee of complete behavioral coverage.

## Migration and compatibility

Existing databases must apply the new migration:

```powershell
python manage.py migrate
```

Docker's web startup runs migrations automatically. Any existing bills with amounts at or below zero must be corrected before the constraint can be added. No existing records were silently rewritten.

The six reported functional defects are fixed. The development settings still produce Django warnings W002, W004, W008, W009, W012, W016, and W018. Customer-level access control, cascading deletion of audit history, and lifetime timeout retry policy remain product-design limitations described in the initial review; they were not among the six functional fixes.

## Evidence

These generated reports are optional and may be absent after cleanup. Run the checks below to regenerate local reports.

- [Full pytest output](../test-results/pytest.txt)
- [JUnit XML](../test-results/junit.xml)
- [Linux container suite](../test-results/docker-tests.txt)
- [Coverage summary](../test-results/coverage.txt)
- [HTML coverage](../test-results/htmlcov/index.html)
- [Live smoke output](../test-results/smoke.txt)
- [Applied migrations](../test-results/applied-migrations.txt)
- [Django check](../test-results/django-check.txt)
- [Migration check](../test-results/migration-check.txt)
- [Deployment check](../test-results/deploy-check.txt)
- [Docker logs](../test-results/docker.log)

## Reproduce

```powershell
docker compose -p utilitypay-test -f deploy/compose.test.yml up -d --build
powershell -ExecutionPolicy Bypass -File scripts/run-tests.ps1
docker compose -p utilitypay-test -f deploy/compose.test.yml exec -T web pytest -q
.venv\Scripts\python.exe scripts/smoke-test.py
docker compose -p utilitypay-test -f deploy/compose.test.yml stop
```

The local runner requires the virtual environment with requirements.txt and coverage installed. Wait for Gunicorn startup before the smoke test. Test services use isolated localhost ports 55432, 56379, and 58000.

## Limits

This verification does not establish production load capacity, penetration-test completeness, dependency CVE status, real payment provider behavior, or every possible concurrency interleaving. The live queue test covers successful reconciliation; timeout worker retry exhaustion is tested eagerly, while timeout persistence is also checked through live HTTP.

