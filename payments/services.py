from datetime import timedelta
import logging

from django.db import transaction
from django.utils import timezone

from .models import Bill, Payment, ReconciliationEvent
from .provider import verify_payment

logger = logging.getLogger(__name__)
MAX_TIMEOUT_ATTEMPTS = 4


def lock_payment(payment_id):
    """All mutations lock bill before payment; caller must hold a transaction."""
    bill_id = Payment.objects.values_list('bill_id', flat=True).get(pk=payment_id)
    bill = Bill.objects.select_for_update().get(pk=bill_id)
    payment = Payment.objects.select_for_update().get(pk=payment_id)
    payment.bill = bill
    return payment


def record_decision(payment, old_status, message):
    if old_status != payment.reconciliation_status:
        ReconciliationEvent.objects.create(
            payment=payment, action='RECONCILE', previous_status=old_status,
            new_status=payment.reconciliation_status, message=message,
        )
        logger.info('Reconciliation payment=%s previous=%s result=%s',
                    payment.pk, old_status, payment.reconciliation_status)


def reconcile_payment(payment_id, *, scheduled=False):
    timeout_message = None
    with transaction.atomic():
        payment = lock_payment(payment_id)
        old_status = payment.reconciliation_status
        if old_status == Payment.ReconciliationStatus.RECONCILED:
            return payment
        if scheduled and (old_status != Payment.ReconciliationStatus.PENDING
                          or payment.next_attempt_at > timezone.now()):
            return payment
        try:
            provider_status = verify_payment(payment)
        except TimeoutError as error:
            if payment.timeout_attempts >= MAX_TIMEOUT_ATTEMPTS:
                return payment
            payment.timeout_attempts += 1
            payment.last_error = str(error)
            payment.next_attempt_at = timezone.now() + timedelta(seconds=2 ** payment.timeout_attempts)
            if payment.timeout_attempts >= MAX_TIMEOUT_ATTEMPTS:
                payment.reconciliation_status = Payment.ReconciliationStatus.MANUAL_REVIEW
                record_decision(payment, old_status, 'Provider timeout budget exhausted; operator review required.')
            else:
                timeout_message = str(error)
                # One event per attempt, protected by the payment lock and persistent budget.
                ReconciliationEvent.objects.create(
                    payment=payment, action='PROVIDER_TIMEOUT', previous_status=old_status,
                    new_status=old_status, message=f'Provider timeout on attempt {payment.timeout_attempts}; retry scheduled.',
                )
            payment.save()
        else:
            payment.last_error = ''
            if provider_status == Payment.ProviderStatus.PENDING:
                payment.next_attempt_at = timezone.now() + timedelta(seconds=60)
                payment.save(update_fields=['last_error', 'next_attempt_at'])
                return payment
            if provider_status == Payment.ProviderStatus.FAILED:
                payment.reconciliation_status = Payment.ReconciliationStatus.FAILED
                message = 'Provider reports payment failed; bill unchanged.'
            elif payment.amount != payment.bill.amount:
                payment.reconciliation_status = Payment.ReconciliationStatus.MANUAL_REVIEW
                message = 'Payment amount does not match bill amount; bill unchanged.'
            elif payment.bill.status == Bill.Status.PAID:
                payment.reconciliation_status = Payment.ReconciliationStatus.MANUAL_REVIEW
                message = 'Bill already paid; possible duplicate payment requires review.'
            else:
                payment.reconciliation_status = Payment.ReconciliationStatus.RECONCILED
                payment.reconciled_at = timezone.now()
                payment.bill.status = Bill.Status.PAID
                payment.bill.save(update_fields=['status'])
                message = 'Provider success and matching amount verified; bill marked paid.'
            payment.save()
            record_decision(payment, old_status, message)
    # API calls and tasks persist the diagnostic before a retryable exception is raised.
    if timeout_message:
        raise TimeoutError(timeout_message)
    return payment
