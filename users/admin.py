from django.contrib import admin
from .models import Customer, PricingRule


admin.site.register(Customer)
admin.site.register(PricingRule)