from django.db import models
from django.utils import timezone
class Customer(models.Model):
 customer_number=models.CharField(max_length=32,unique=True); name=models.CharField(max_length=120); email=models.EmailField()
 created_at=models.DateTimeField(default=timezone.now,editable=False)
 def __str__(self): return self.customer_number
class Bill(models.Model):
 class Status(models.TextChoices): UNPAID='UNPAID'; PAID='PAID'
 customer=models.ForeignKey(Customer,on_delete=models.PROTECT,related_name='bills'); bill_number=models.CharField(max_length=32,unique=True); amount=models.DecimalField(max_digits=12,decimal_places=2); due_date=models.DateField(); status=models.CharField(max_length=10,choices=Status.choices,default=Status.UNPAID)
 created_at=models.DateTimeField(default=timezone.now,editable=False)
 class Meta:
  constraints=[models.CheckConstraint(condition=models.Q(amount__gt=0),name='bill_amount_positive'), models.CheckConstraint(condition=models.Q(status__in=['UNPAID','PAID']),name='bill_status_valid')]
class Payment(models.Model):
 class ProviderStatus(models.TextChoices): SUCCESS='SUCCESS'; FAILED='FAILED'; PENDING='PENDING'; TIMEOUT='TIMEOUT'
 class ReconciliationStatus(models.TextChoices): PENDING='PENDING'; RECONCILED='RECONCILED'; FAILED='FAILED'; MANUAL_REVIEW='MANUAL_REVIEW'
 bill=models.ForeignKey(Bill,on_delete=models.PROTECT,related_name='payments'); provider_reference=models.CharField(max_length=64,unique=True); amount=models.DecimalField(max_digits=12,decimal_places=2); provider_status=models.CharField(max_length=10,choices=ProviderStatus.choices); reconciliation_status=models.CharField(max_length=20,choices=ReconciliationStatus.choices,default=ReconciliationStatus.PENDING); created_at=models.DateTimeField(auto_now_add=True); reconciled_at=models.DateTimeField(null=True,blank=True); last_error=models.TextField(blank=True)
 timeout_attempts=models.PositiveSmallIntegerField(default=0,editable=False)
 next_attempt_at=models.DateTimeField(default=timezone.now,editable=False)
 simulated_timeouts=models.PositiveSmallIntegerField(default=0,help_text='Number of temporary timeouts before the configured provider result (0-3).')
 class Meta:
  indexes=[models.Index(fields=['reconciliation_status','next_attempt_at'],name='payment_due_idx')]
  constraints=[
   models.CheckConstraint(condition=models.Q(amount__gt=0),name='payment_amount_positive'),
   models.CheckConstraint(condition=models.Q(provider_status__in=['SUCCESS','FAILED','PENDING','TIMEOUT']),name='provider_status_valid'),
   models.CheckConstraint(condition=models.Q(reconciliation_status__in=['PENDING','RECONCILED','FAILED','MANUAL_REVIEW']),name='reconciliation_status_valid'),
   models.CheckConstraint(condition=models.Q(simulated_timeouts__lte=3),name='simulated_timeouts_bounded'),
   models.UniqueConstraint(fields=['bill'],condition=models.Q(reconciliation_status='RECONCILED'),name='one_reconciled_payment_per_bill'),
  ]
class ReconciliationEvent(models.Model):
 payment=models.ForeignKey(Payment,on_delete=models.PROTECT,related_name='events'); action=models.CharField(max_length=40); previous_status=models.CharField(max_length=20,blank=True); new_status=models.CharField(max_length=20,blank=True); message=models.TextField(blank=True); created_at=models.DateTimeField(auto_now_add=True)
