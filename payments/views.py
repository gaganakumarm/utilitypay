from django.db import transaction, connection
from django.db.models.deletion import ProtectedError
from django.conf import settings
from redis import Redis
from rest_framework.exceptions import APIException
from django.http import Http404
from rest_framework import viewsets,status
from rest_framework.decorators import action,api_view,permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import Customer,Bill,Payment,ReconciliationEvent
from .serializers import CustomerSerializer,BillSerializer,PaymentSerializer,EventSerializer
from .services import reconcile_payment, lock_payment
@api_view(['GET'])
@permission_classes([AllowAny])
def health(request): return Response({'status':'ok'})
class Conflict(APIException):
 status_code=409
 default_detail='Related financial records or audit history prevent deletion.'

class ProtectedViewSet(viewsets.ModelViewSet):
 def perform_destroy(self,instance):
  try: instance.delete()
  except ProtectedError as error: raise Conflict() from error

class CustomerViewSet(ProtectedViewSet): queryset=Customer.objects.all().order_by('id'); serializer_class=CustomerSerializer
class BillViewSet(ProtectedViewSet):
 queryset=Bill.objects.select_related('customer').all().order_by('-id')
 serializer_class=BillSerializer
 filterset_fields=['status','customer']
 def get_queryset(self):
  queryset=super().get_queryset()
  return queryset.select_for_update(of=('self',)) if self.action in ('update','partial_update') else queryset
 @transaction.atomic
 def update(self,request,*args,**kwargs):
  return super().update(request,*args,**kwargs)
class PaymentViewSet(ProtectedViewSet):
 queryset=Payment.objects.select_related('bill').all().order_by('-id'); serializer_class=PaymentSerializer; filterset_fields=['provider_status','reconciliation_status','bill']
 def get_object(self):
  instance=super().get_object()
  if self.action in ('update','partial_update','destroy'):
   try: return lock_payment(instance.pk)
   except Payment.DoesNotExist: raise Http404('Payment not found.')
  return instance
 @transaction.atomic
 def update(self,request,*args,**kwargs):
  return super().update(request,*args,**kwargs)
 @transaction.atomic
 def destroy(self,request,*args,**kwargs):
  return super().destroy(request,*args,**kwargs)
 @transaction.atomic
 def perform_create(self,serializer):
  Bill.objects.select_for_update().get(pk=serializer.validated_data['bill'].pk)
  serializer.save()
 @action(detail=True,methods=['post'])
 def reconcile(self,request,pk=None):
  payment = self.get_object()
  try: p=reconcile_payment(payment.pk)
  except Payment.DoesNotExist: raise Http404('Payment not found.')
  except TimeoutError as e: return Response({'detail':str(e)},status=status.HTTP_503_SERVICE_UNAVAILABLE)
  return Response(self.get_serializer(p).data)
class EventViewSet(viewsets.ReadOnlyModelViewSet): queryset=ReconciliationEvent.objects.select_related('payment').all().order_by('-id'); serializer_class=EventSerializer; filterset_fields=['payment','action']


@api_view(['GET'])
@permission_classes([AllowAny])
def ready(request):
 checks={}
 try:
  with connection.cursor() as cursor:
   cursor.execute('SELECT 1')
  checks['database']='ok'
 except Exception:
  checks['database']='unavailable'
 try:
  with Redis.from_url(settings.CELERY_BROKER_URL,socket_connect_timeout=2,socket_timeout=2) as redis:
   redis.ping()
  checks['redis']='ok'
 except Exception:
  checks['redis']='unavailable'
 healthy=all(value=='ok' for value in checks.values())
 return Response({'status':'ok' if healthy else 'unavailable','checks':checks},status=200 if healthy else 503)
