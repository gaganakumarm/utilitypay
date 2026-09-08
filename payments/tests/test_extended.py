from datetime import date
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from payments.models import Bill, Customer, Payment, ReconciliationEvent
from payments.services import reconcile_payment
from payments.tasks import reconcile_pending_payments, reconcile_payment_task

pytestmark = pytest.mark.django_db


@pytest.fixture
def bill():
    customer = Customer.objects.create(customer_number='EXT1', name='Test', email='test@example.com')
    return Bill.objects.create(customer=customer, bill_number='EXT1', amount='100.00', due_date=date.today())


@pytest.fixture
def client():
    user = get_user_model().objects.create_user(username='extended', password='test12345')
    api = APIClient()
    api.force_authenticate(user)
    return api


def payment(bill, state='SUCCESS', amount='100.00'):
    return Payment.objects.create(bill=bill, provider_reference='EXT1', amount=amount, provider_status=state)


@pytest.mark.parametrize('endpoint', ['customers', 'bills', 'payments', 'reconciliations'])
def test_all_resources_require_auth(endpoint):
    assert APIClient().get(f'/api/{endpoint}/').status_code == 401


def test_public_health():
    response = APIClient().get('/health/')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_invalid_login():
    assert APIClient().post('/api/auth/token/', {'username': 'missing', 'password': 'bad'}).status_code == 401


def test_refresh_token():
    get_user_model().objects.create_user(username='refresh', password='test12345')
    api = APIClient()
    tokens = api.post('/api/auth/token/', {'username': 'refresh', 'password': 'test12345'}).json()
    response = api.post('/api/auth/token/refresh/', {'refresh': tokens['refresh']})
    assert response.status_code == 200
    assert response.json()['access']


@pytest.mark.parametrize('amount', ['0', '-1', 'abc', '1.001'])
def test_invalid_payment_amount(client, bill, amount):
    response = client.post('/api/payments/', {'bill': bill.pk, 'provider_reference': 'NEW', 'amount': amount, 'provider_status': 'SUCCESS'})
    assert response.status_code == 400


def test_duplicate_reference(client, bill):
    payment(bill)
    assert client.post('/api/payments/', {'bill': bill.pk, 'provider_reference': 'EXT1', 'amount': '100', 'provider_status': 'SUCCESS'}).status_code == 400


@pytest.mark.parametrize('overrides', [{'provider_status': 'INVALID'}, {'bill': 999999}, {'provider_reference': ''}])
def test_invalid_payment_fields(client, bill, overrides):
    payload = {'bill': bill.pk, 'provider_reference': 'NEW', 'amount': '100', 'provider_status': 'SUCCESS'}
    payload.update(overrides)
    assert client.post('/api/payments/', payload).status_code == 400


def test_bill_and_payment_crud(client, bill):
    response = client.post('/api/bills/', {'customer': bill.customer_id, 'bill_number': 'CRUD2', 'amount': '20', 'due_date': '2026-12-31'})
    assert response.status_code == 201
    bill_url = f"/api/bills/{response.json()['id']}/"
    assert client.patch(bill_url, {'amount': '25'}).status_code == 200
    response = client.post('/api/payments/', {'bill': response.json()['id'], 'provider_reference': 'CRUD2', 'amount': '25', 'provider_status': 'PENDING'})
    assert response.status_code == 201
    payment_url = f"/api/payments/{response.json()['id']}/"
    assert client.get(payment_url).status_code == 200
    assert client.patch(payment_url, {'provider_status': 'SUCCESS'}).status_code == 200
    assert client.delete(payment_url).status_code == 204
    assert client.delete(bill_url).status_code == 204


def test_invalid_bearer_token():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')
    assert api.get('/api/payments/').status_code == 401


def test_read_only_state(client, bill):
    p = payment(bill, 'PENDING')
    assert client.patch(f'/api/bills/{bill.pk}/', {'status': 'PAID'}).status_code == 200
    assert client.patch(f'/api/payments/{p.pk}/', {'reconciliation_status': 'RECONCILED', 'last_error': 'injected'}).status_code == 200
    bill.refresh_from_db()
    p.refresh_from_db()
    assert bill.status == 'UNPAID'
    assert p.reconciliation_status == 'PENDING'
    assert p.last_error == ''


def test_manual_success_and_event(client, bill):
    p = payment(bill)
    assert client.post(f'/api/payments/{p.pk}/reconcile/').status_code == 200
    event = ReconciliationEvent.objects.get(payment=p)
    assert (event.previous_status, event.new_status) == ('PENDING', 'RECONCILED')
    p.refresh_from_db()
    assert p.reconciled_at is not None
    assert client.post('/api/reconciliations/', {}).status_code == 405


@pytest.mark.parametrize('detail', [False, True])
def test_audit_api_read(client, bill, detail):
    p = payment(bill)
    reconcile_payment(p.pk)
    event = ReconciliationEvent.objects.get(payment=p)
    client.raise_request_exception = False
    url = f'/api/reconciliations/{event.pk}/' if detail else '/api/reconciliations/'
    assert client.get(url).status_code == 200


def test_timeout_api(client, bill):
    p = payment(bill, 'TIMEOUT')
    assert client.post(f'/api/payments/{p.pk}/reconcile/').status_code == 503
    bill.refresh_from_db()
    assert bill.status == 'UNPAID'


def test_filter_payments(client, bill):
    payment(bill)
    assert len(client.get('/api/payments/?provider_status=SUCCESS').json()) == 1
    assert client.get('/api/payments/?provider_status=FAILED').json() == []


def test_queue_only_pending(bill):
    p = payment(bill)
    Payment.objects.create(bill=bill, provider_reference='DONE', amount='100', provider_status='SUCCESS', reconciliation_status='RECONCILED')
    with patch('payments.tasks.reconcile_payment_task.delay') as delay:
        assert reconcile_pending_payments() == 1
        delay.assert_called_once_with(p.pk)


def test_task_success(bill):
    p = payment(bill)
    assert reconcile_payment_task.apply(args=[p.pk]).get() == 'RECONCILED'


def test_atomic_rollback(bill):
    p = payment(bill)
    with patch('payments.services.ReconciliationEvent.objects.create', side_effect=RuntimeError('audit unavailable')):
        with pytest.raises(RuntimeError):
            reconcile_payment(p.pk)
    p.refresh_from_db()
    bill.refresh_from_db()
    assert p.reconciliation_status == 'PENDING'
    assert bill.status == 'UNPAID'


# Regression expectations for previously reported application defects.
def test_timeout_error_is_persisted(bill):
    p = payment(bill, 'TIMEOUT')
    with pytest.raises(TimeoutError):
        reconcile_payment(p.pk)
    p.refresh_from_db()
    assert p.last_error == 'Provider temporarily unavailable'


@pytest.mark.parametrize('state,amount', [('FAILED', '100.00'), ('SUCCESS', '99.00')])
def test_repeated_terminal_outcome_has_one_event(bill, state, amount):
    p = payment(bill, state, amount)
    reconcile_payment(p.pk)
    reconcile_payment(p.pk)
    assert p.events.count() == 1


def test_missing_reconcile_returns_404(client):
    client.raise_request_exception = False
    assert client.post('/api/payments/999999/reconcile/').status_code == 404


def test_reconciled_payment_rejects_amount_change(client, bill):
    p = payment(bill)
    reconcile_payment(p.pk)
    assert client.patch(f'/api/payments/{p.pk}/', {'amount': '1.00'}).status_code == 400


def test_bill_rejects_negative_amount(client, bill):
    assert client.patch(f'/api/bills/{bill.pk}/', {'amount': '-1.00'}).status_code == 400


@pytest.mark.parametrize('amount', ['0.00', '-1.00'])
def test_bill_database_rejects_nonpositive_amount(bill, amount):
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        Bill.objects.filter(pk=bill.pk).update(amount=amount)


@pytest.mark.parametrize('amount', ['0.00', '-1.00'])
def test_create_bill_rejects_nonpositive_amount(client, bill, amount):
    assert client.post('/api/bills/', {'customer': bill.customer_id, 'bill_number': 'BAD', 'amount': amount, 'due_date': '2026-12-31'}).status_code == 400


@pytest.mark.parametrize('field,value', [('provider_status', 'FAILED'), ('provider_reference', 'EDITED'), ('bill', None)])
def test_reconciled_payment_rejects_other_changes(client, bill, field, value):
    p = payment(bill)
    reconcile_payment(p.pk)
    if field == 'bill':
        value = Bill.objects.create(customer=bill.customer, bill_number='OTHER', amount='100', due_date=date.today()).pk
    assert client.patch(f'/api/payments/{p.pk}/', {field: value}).status_code == 400
    p.refresh_from_db()
    assert p.bill_id == bill.pk
    assert p.provider_status == 'SUCCESS'
    assert p.provider_reference == 'EXT1'


def test_reconciled_payment_put_and_unchanged_patch(client, bill):
    p = payment(bill)
    reconcile_payment(p.pk)
    url = f'/api/payments/{p.pk}/'
    payload = {'bill': bill.pk, 'provider_reference': p.provider_reference, 'provider_status': 'SUCCESS', 'amount': '1.00'}
    assert client.put(url, payload).status_code == 400
    assert client.patch(url, {'amount': '100.00'}).status_code == 200


@pytest.mark.parametrize('next_state', ['SUCCESS', 'PENDING', 'FAILED'])
def test_timeout_recovery_clears_error(bill, next_state):
    p = payment(bill, 'TIMEOUT')
    with pytest.raises(TimeoutError):
        reconcile_payment(p.pk)
    p.refresh_from_db()
    assert p.last_error
    p.provider_status = next_state
    p.save(update_fields=['provider_status'])
    reconcile_payment(p.pk)
    p.refresh_from_db()
    assert p.last_error == ''


@pytest.mark.parametrize('state,amount', [('FAILED', '100.00'), ('SUCCESS', '99.00')])
def test_corrected_terminal_payment_can_reconcile(client, bill, state, amount):
    p = payment(bill, state, amount)
    reconcile_payment(p.pk)
    assert client.patch(f'/api/payments/{p.pk}/', {'provider_status': 'SUCCESS', 'amount': '100.00'}).status_code == 200
    reconcile_payment(p.pk)
    p.refresh_from_db()
    assert p.reconciliation_status == 'RECONCILED'
    assert p.events.count() == 2


def test_timeout_api_persists_diagnostic(client, bill):
    p = payment(bill, 'TIMEOUT')
    assert client.post(f'/api/payments/{p.pk}/reconcile/').status_code == 503
    assert client.get(f'/api/payments/{p.pk}/').json()['last_error'] == 'Provider temporarily unavailable'


def test_customer_crud(client):
    response = client.post('/api/customers/', {'customer_number': 'CRUD', 'name': 'Before', 'email': 'crud@example.com'})
    assert response.status_code == 201
    url = f"/api/customers/{response.json()['id']}/"
    assert client.get(url).status_code == 200
    assert client.patch(url, {'name': 'After'}).json()['name'] == 'After'
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_another_user_can_access_customer(client, bill):
    other = get_user_model().objects.create_user(username='other', password='test12345')
    client.force_authenticate(other)
    assert client.get(f'/api/customers/{bill.customer_id}/').status_code == 200


def test_related_records_cannot_delete_audit(client, bill):
    p = payment(bill)
    reconcile_payment(p.pk)
    for url in (f'/api/customers/{bill.customer_id}/', f'/api/bills/{bill.pk}/', f'/api/payments/{p.pk}/'):
        assert client.delete(url).status_code == 409
    assert ReconciliationEvent.objects.count() == 1
    assert Payment.objects.count() == 1
    assert Bill.objects.count() == 1


def test_timeout_task_stops_until_next_due_time(bill):
    p = payment(bill, 'TIMEOUT')
    result = reconcile_payment_task.apply(args=[p.pk])
    assert result.successful()
    p.refresh_from_db()
    assert p.timeout_attempts == 1
    assert p.reconciliation_status == 'PENDING'
    assert p.events.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_reconciliation():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import connection, connections

    if connection.vendor != 'postgresql':
        pytest.skip('Requires PostgreSQL row locks')
    c = Customer.objects.create(customer_number='RACE', name='Race', email='race@example.com')
    b = Bill.objects.create(customer=c, bill_number='RACE', amount='100', due_date=date.today())
    p = payment(b)
    barrier = Barrier(2)

    def run():
        try:
            barrier.wait(timeout=10)
            return reconcile_payment(p.pk).reconciliation_status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results == ['RECONCILED', 'RECONCILED']
    assert p.events.count() == 1
    b.refresh_from_db()
    assert b.status == 'PAID'
