# Resolve project paths from this script, including when launched elsewhere.
Push-Location (Split-Path -Parent $PSScriptRoot)
try {
$env:POSTGRES_HOST = '127.0.0.1'
$env:POSTGRES_PORT = '55432'
$env:POSTGRES_DB = 'utilitypay_test'
$env:POSTGRES_USER = 'utilitypay'
$env:POSTGRES_PASSWORD = 'utilitypay_test_only'
$env:REDIS_URL = 'redis://127.0.0.1:56379/0'
$env:DJANGO_SECRET_KEY = 'isolated-test-secret-key-at-least-32-characters'
New-Item -ItemType Directory -Force test-results | Out-Null
& .venv\Scripts\python.exe -m coverage run --branch --source=payments,utilitypay -m pytest -v --tb=short --junitxml=test-results/junit.xml *> test-results/pytest.txt
$testExitCode = $LASTEXITCODE
Get-Content test-results/pytest.txt
& .venv\Scripts\python.exe -m coverage report --omit='payments/tests/*' -m | Tee-Object test-results/coverage.txt
& .venv\Scripts\python.exe -m coverage html --omit='payments/tests/*' -d test-results/htmlcov
& .venv\Scripts\python.exe manage.py check *> test-results/django-check.txt
& .venv\Scripts\python.exe manage.py check --deploy *> test-results/deploy-check.txt
& .venv\Scripts\python.exe manage.py makemigrations --check --dry-run *> test-results/migration-check.txt
} finally {
 Pop-Location
}
exit $testExitCode
