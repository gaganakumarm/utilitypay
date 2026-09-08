from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from payments.views import health, ready
urlpatterns=[path('ready/',ready),path('api-auth/',include('rest_framework.urls')),path('admin/',admin.site.urls),path('health/',health),path('api/auth/token/',TokenObtainPairView.as_view()),path('api/auth/token/refresh/',TokenRefreshView.as_view()),path('api/',include('payments.urls'))]
