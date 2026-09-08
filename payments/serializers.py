from rest_framework import serializers
from .models import Customer,Bill,Payment,ReconciliationEvent
class CustomerSerializer(serializers.ModelSerializer):
 class Meta: model=Customer; fields='__all__'
class BillSerializer(serializers.ModelSerializer):
 class Meta: model=Bill; fields='__all__'; read_only_fields=['status']
 def validate_amount(self,value):
  if value <= 0: raise serializers.ValidationError('Must be greater than zero.')
  return value
 def validate(self,attrs):
  if self.instance and self.instance.payments.exists():
   for field in ('amount','customer','bill_number'):
    if field in attrs and attrs[field] != getattr(self.instance,field):
     raise serializers.ValidationError({field:'Bills with payment attempts cannot change financial identity.'})
  return attrs
class PaymentSerializer(serializers.ModelSerializer):
 class Meta: model=Payment; fields='__all__'; read_only_fields=['reconciliation_status','reconciled_at','last_error','timeout_attempts','next_attempt_at']
 def validate_simulated_timeouts(self,value):
  if value > 3: raise serializers.ValidationError('Must be between 0 and 3.')
  return value
 def validate(self,attrs):
  if self.instance and 'bill' in attrs and attrs['bill'].pk != self.instance.bill_id:
   raise serializers.ValidationError({'bill':'Payment attempts cannot be moved to another bill.'})
  if attrs.get('amount') is not None and attrs['amount'] <= 0: raise serializers.ValidationError({'amount':'Must be greater than zero.'})
  if self.instance and self.instance.reconciliation_status == Payment.ReconciliationStatus.RECONCILED:
   changed = [field for field in ('bill','amount','provider_reference','provider_status','simulated_timeouts') if field in attrs and attrs[field] != getattr(self.instance,field)]
   if changed: raise serializers.ValidationError({field:'Reconciled payments cannot be changed.' for field in changed})
  return attrs
class EventSerializer(serializers.ModelSerializer):
 class Meta: model=ReconciliationEvent; fields='__all__'; read_only_fields=['id','payment','action','previous_status','new_status','message','created_at']
