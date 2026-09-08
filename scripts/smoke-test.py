"""Exercise the isolated Docker stack over real HTTP and the scheduled worker."""
import json
import time
import urllib.request
import urllib.error
from uuid import uuid4

BASE = 'http://127.0.0.1:58000'
token = None


def request(path, data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


assert request('/health/')[0] == 200
print('PASS: live health', flush=True)
token = request('/api/auth/token/', {'username': 'demo', 'password': 'demo12345'})[1]['access']
print('PASS: live JWT login', flush=True)
suffix = uuid4().hex[:10]
c = request('/api/customers/', {'customer_number': suffix, 'name': 'Smoke', 'email': 'smoke@example.com'})[1]
b = request('/api/bills/', {'customer': c['id'], 'bill_number': suffix, 'amount': '123.45', 'due_date': '2026-12-31'})[1]
p = request('/api/payments/', {'bill': b['id'], 'provider_reference': suffix, 'amount': '123.45', 'provider_status': 'SUCCESS'})[1]
print('PASS: live customer, bill, payment creation', flush=True)
start = time.monotonic()
while time.monotonic() - start < 90:
    result = request(f"/api/payments/{p['id']}/")[1]
    if result['reconciliation_status'] == 'RECONCILED':
        break
    time.sleep(2)
else:
    raise AssertionError('Scheduled reconciliation did not finish within 90 seconds')
assert request(f"/api/bills/{b['id']}/")[1]['status'] == 'PAID'
print(f'PASS: Beat -> Redis -> worker -> paid bill ({time.monotonic() - start:.1f}s)', flush=True)
assert request(f"/api/payments/{p['id']}/reconcile/", {})[0] == 200
assert len(request(f"/api/reconciliations/?payment={p['id']}")[1]) == 1
print('PASS: live repeated reconciliation retains one audit event', flush=True)

timeout_payment = request('/api/payments/', {'bill': b['id'], 'provider_reference': suffix + '-timeout', 'amount': '123.45', 'provider_status': 'TIMEOUT'})[1]
try:
    request(f"/api/payments/{timeout_payment['id']}/reconcile/", {})
except urllib.error.HTTPError as error:
    assert error.code == 503
else:
    raise AssertionError('Expected timeout response')
assert request(f"/api/payments/{timeout_payment['id']}/")[1]['last_error'] == 'Provider temporarily unavailable'
print('PASS: live timeout diagnostic survives HTTP 503', flush=True)
