from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, OperationalError, connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from payments.models import Bill, Customer, Payment, ReconciliationEvent
from payments.services import reconcile_payment
from payments.tasks import reconcile_payment_task, reconcile_pending_payments

pytestmark = pytest.mark.django_db


@pytest.fixture
def bill():
    customer = Customer.objects.create(customer_number='R', name='Reliability', email='r@example.com')
    return Bill.objects.create(customer=customer, bill_number='R', amount='100', due_date=date.today())


def make_payment(bill, reference='R', **kwargs):
    return Payment.objects.create(bill=bill, provider_reference=reference, amount='100', provider_status=kwargs.pop('provider_status', 'SUCCESS'), **kwargs)


def authenticated_client():
    client = APIClient()
    client.force_authenticate(get_user_model().objects.create_user(username='operator'))
    return client


def test_second_success_is_manual_review(bill):
    first = make_payment(bill)
    second = make_payment(bill, 'SECOND')
    reconcile_payment(first.pk)
    result = reconcile_payment(second.pk)
    assert result.reconciliation_status == 'MANUAL_REVIEW'
    assert 'already paid' in result.events.get().message
    reconcile_payment(second.pk)
    assert result.events.count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_payments_on_same_bill_are_serialized(bill):
    payments = [make_payment(bill, reference) for reference in ('ONE', 'TWO')]
    barrier = Barrier(2)

    def run(payment):
        try:
            barrier.wait(timeout=10)
            return reconcile_payment(payment.pk).reconciliation_status
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, payments))
    assert sorted(results) == ['MANUAL_REVIEW', 'RECONCILED']
    assert ReconciliationEvent.objects.count() == 2


def test_timeout_budget_survives_task_redelivery(bill):
    payment = make_payment(bill, provider_status='TIMEOUT')
    for attempt in range(4):
        Payment.objects.filter(pk=payment.pk).update(next_attempt_at=timezone.now()-timedelta(seconds=1))
        reconcile_payment_task.apply(args=[payment.pk]).get()
    payment.refresh_from_db()
    assert payment.timeout_attempts == 4
    assert payment.reconciliation_status == 'MANUAL_REVIEW'
    assert payment.events.count() == 4
    for _ in range(3):
        reconcile_payment_task.apply(args=[payment.pk]).get()
        reconcile_payment(payment.pk)
    assert payment.events.count() == 4
    with patch('payments.tasks.reconcile_payment_task.delay') as delay:
        assert reconcile_pending_payments() == 0
        delay.assert_not_called()


def test_transient_provider_recovers(bill):
    payment = make_payment(bill, simulated_timeouts=2)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            reconcile_payment(payment.pk)
    result = reconcile_payment(payment.pk)
    assert result.reconciliation_status == 'RECONCILED'
    assert result.last_error == ''
    assert result.timeout_attempts == 2
    assert result.events.count() == 3


def test_transient_database_failure_retried(bill):
    payment = make_payment(bill)
    with patch('payments.tasks.reconcile_payment', side_effect=[OperationalError('temporary'), payment]) as reconcile:
        result = reconcile_payment_task.apply(args=[payment.pk])
    assert result.successful()
    assert reconcile.call_count == 2


def test_missing_task_is_harmless():
    assert reconcile_payment_task.apply(args=[999999]).get() == 'MISSING'


def test_future_payments_are_not_enqueued(bill):
    make_payment(bill, next_attempt_at=timezone.now()+timedelta(hours=1))
    with patch('payments.tasks.reconcile_payment_task.delay') as delay:
        assert reconcile_pending_payments() == 0
        delay.assert_not_called()


@pytest.mark.parametrize('field,value', [('amount', '-1'), ('provider_status', 'BAD'), ('reconciliation_status', 'BAD'), ('simulated_timeouts', 4)])
def test_database_payment_constraints(bill, field, value):
    payment = make_payment(bill)
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.filter(pk=payment.pk).update(**{field: value})


def test_database_unique_reconciled_bill(bill):
    first = make_payment(bill)
    second = make_payment(bill, 'SECOND')
    reconcile_payment(first.pk)
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.filter(pk=second.pk).update(reconciliation_status='RECONCILED')


def test_bill_financial_identity_locked_after_attempt(bill):
    make_payment(bill)
    client = authenticated_client()
    for data in ({'amount': '101'}, {'bill_number': 'CHANGED'}):
        assert client.patch(f'/api/bills/{bill.pk}/', data).status_code == 400
    assert client.patch(f'/api/bills/{bill.pk}/', {'due_date': '2027-01-01'}).status_code == 200


def test_unreconciled_payment_cannot_move_bill(bill):
    payment = make_payment(bill)
    other = Bill.objects.create(customer=bill.customer, bill_number='OTHER', amount='100', due_date=date.today())
    assert authenticated_client().patch(f'/api/payments/{payment.pk}/', {'bill': other.pk}).status_code == 400


def test_seed_idempotent_and_password_preserved():
    call_command('seed_demo')
    user = get_user_model().objects.get(username='demo')
    user.set_password('changed-secret')
    user.save()
    call_command('seed_demo')
    assert Payment.objects.count() == 6
    assert Bill.objects.count() == 6
    user.refresh_from_db()
    assert user.check_password('changed-secret')


@pytest.mark.parametrize('available', [True, False])
def test_readiness_redis_outage(available):
    with patch('payments.views.Redis.from_url') as redis:
        if not available:
            redis.return_value.__enter__.return_value.ping.side_effect = ConnectionError('private details')
        result = APIClient().get('/ready/')
    assert result.status_code == (200 if available else 503)
    assert 'private details' not in str(result.data)


def test_audit_api_cannot_modify_or_delete(bill):
    payment = make_payment(bill)
    reconcile_payment(payment.pk)
    event = payment.events.get()
    client = authenticated_client()
    assert client.patch(f'/api/reconciliations/{event.pk}/', {'message': 'tamper'}).status_code == 405
    assert client.delete(f'/api/reconciliations/{event.pk}/').status_code == 405
