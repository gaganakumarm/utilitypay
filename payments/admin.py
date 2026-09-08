from django.contrib import admin
from .models import Customer, Bill, Payment, ReconciliationEvent


class ReadOnlyFinancialAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Customer)
for model in (Bill, Payment, ReconciliationEvent):
    admin.site.register(model, ReadOnlyFinancialAdmin)
