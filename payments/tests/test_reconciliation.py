import pytest
from datetime import date
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from payments.models import Customer,Bill,Payment,ReconciliationEvent
from payments.services import reconcile_payment
@pytest.fixture
def data(db):
 c=Customer.objects.create(customer_number='C1',name='A',email='a@x.com'); b=Bill.objects.create(customer=c,bill_number='B1',amount='100.00',due_date=date.today()); return b
@pytest.mark.django_db
def test_success_reconciles_and_is_idempotent(data):
 p=Payment.objects.create(bill=data,provider_reference='P1',amount='100.00',provider_status='SUCCESS'); reconcile_payment(p.id); reconcile_payment(p.id); p.refresh_from_db(); data.refresh_from_db(); assert p.reconciliation_status=='RECONCILED'; assert data.status=='PAID'; assert ReconciliationEvent.objects.count()==1
@pytest.mark.django_db
def test_amount_mismatch_manual_review(data):
 p=Payment.objects.create(bill=data,provider_reference='P2',amount='99.00',provider_status='SUCCESS'); reconcile_payment(p.id); p.refresh_from_db(); data.refresh_from_db(); assert p.reconciliation_status=='MANUAL_REVIEW'; assert data.status=='UNPAID'
@pytest.mark.django_db
def test_failed_provider(data):
 p=Payment.objects.create(bill=data,provider_reference='P3',amount='100.00',provider_status='FAILED'); reconcile_payment(p.id); p.refresh_from_db(); assert p.reconciliation_status=='FAILED'
@pytest.mark.django_db
def test_pending_is_noop(data):
 p=Payment.objects.create(bill=data,provider_reference='P4',amount='100.00',provider_status='PENDING'); reconcile_payment(p.id); p.refresh_from_db(); assert p.reconciliation_status=='PENDING'; assert ReconciliationEvent.objects.count()==0
@pytest.mark.django_db
def test_timeout_raises(data):
 p=Payment.objects.create(bill=data,provider_reference='P5',amount='100.00',provider_status='TIMEOUT');
 with pytest.raises(TimeoutError): reconcile_payment(p.id)
@pytest.mark.django_db
def test_api_requires_auth(data):
 assert APIClient().get('/api/bills/').status_code==401
@pytest.mark.django_db
def test_jwt_and_list(data):
 u=get_user_model().objects.create_user(username='u',password='pass12345'); client=APIClient(); token=client.post('/api/auth/token/',{'username':'u','password':'pass12345'},format='json').json()['access']; client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}'); assert client.get('/api/bills/').status_code==200
