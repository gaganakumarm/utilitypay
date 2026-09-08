from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet,BillViewSet,PaymentViewSet,EventViewSet
r=DefaultRouter(); r.register('customers',CustomerViewSet); r.register('bills',BillViewSet); r.register('payments',PaymentViewSet); r.register('reconciliations',EventViewSet)
urlpatterns=r.urls
