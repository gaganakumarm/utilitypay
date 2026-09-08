from celery import shared_task
from django.db import OperationalError
from django.utils import timezone

from .models import Payment
from .services import reconcile_payment


@shared_task(bind=True, autoretry_for=(TimeoutError, OperationalError), retry_backoff=True,
             retry_jitter=True, retry_kwargs={'max_retries': 3}, acks_late=True)
def reconcile_payment_task(self, payment_id):
    try:
        return reconcile_payment(payment_id, scheduled=True).reconciliation_status
    except Payment.DoesNotExist:
        return 'MISSING'


@shared_task
def reconcile_pending_payments():
    ids = Payment.objects.filter(
        reconciliation_status=Payment.ReconciliationStatus.PENDING,
        next_attempt_at__lte=timezone.now(),
    ).order_by('next_attempt_at').values_list('id', flat=True)[:500]
    count = 0
    for payment_id in ids:
        reconcile_payment_task.delay(payment_id)
        count += 1
    return count
