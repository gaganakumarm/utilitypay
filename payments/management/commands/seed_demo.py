import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.models import Customer, Bill, Payment


class Command(BaseCommand):
    help = 'Create an operator and deterministic reconciliation examples without resetting existing data.'

    def handle(self, *args, **kwargs):
        user, created = get_user_model().objects.get_or_create(username='demo')
        if created:
            user.set_password(os.getenv('DEMO_PASSWORD', 'demo12345'))
            user.save(update_fields=['password'])
        customer, _ = Customer.objects.get_or_create(
            customer_number='CUST-1001', defaults={'name': 'Demo Customer', 'email': 'demo@example.com'})
        scenarios = [
            ('1001', 'SUCCESS', '1850.00', 0),
            ('MISMATCH', 'SUCCESS', '1800.00', 0),
            ('FAILED', 'FAILED', '1850.00', 0),
            ('PENDING', 'PENDING', '1850.00', 0),
            ('TIMEOUT', 'TIMEOUT', '1850.00', 0),
            ('RECOVERY', 'SUCCESS', '1850.00', 2),
        ]
        for suffix, provider_status, amount, timeouts in scenarios:
            bill, _ = Bill.objects.get_or_create(
                bill_number=f'BILL-{suffix}', defaults={'customer': customer,
                    'amount': '1850.00', 'due_date': timezone.localdate() + timedelta(days=7)})
            reference = 'PAY-SUCCESS-1001' if suffix == '1001' else f'PAY-{suffix}'
            Payment.objects.get_or_create(provider_reference=reference,
                defaults={'bill': bill, 'amount': amount, 'provider_status': provider_status,
                          'simulated_timeouts': timeouts})
        self.stdout.write(self.style.SUCCESS('Demo operator and six scenarios ready; existing records preserved.'))
