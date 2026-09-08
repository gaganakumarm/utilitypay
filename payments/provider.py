"""Deterministic provider simulator: no network calls or financial credentials."""
from .models import Payment


def verify_payment(payment):
    if (payment.provider_status == Payment.ProviderStatus.TIMEOUT
            or payment.timeout_attempts < payment.simulated_timeouts):
        raise TimeoutError('Provider temporarily unavailable')
    return payment.provider_status
