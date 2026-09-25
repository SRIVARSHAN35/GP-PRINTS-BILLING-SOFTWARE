from django.urls import path
from . import views

urlpatterns = [

    path("",views.loginpage, name="loginpage"),

    path("dashboard/",views.dashboard, name="dashboard"),

    path("reports/", views.reports, name="reports"),

    path("reports/edit/<int:id>/", views.edit_bill, name="edit_bill"),

    path("reports/delete/<int:id>/", views.delete_bill, name="delete_bill"),

    path("settings/", views.settings_page, name="settings_page"),

    path("settings/add-field/", views.add_pricing_rule, name="add_pricing_rule"),

    path("settings/request-email-change/", views.request_email_change, name="request_email_change"),

    path("settings/verify-email-change/", views.verify_email_change, name="verify_email_change"),


    # CUSTOMERS

    path("customers/", views.customer_list, name="customer_list"),

    path("customers/add/", views.add_customer, name="add_customer"),

    path("customers/edit/<int:id>/",views.edit_customer,name="edit_customer"),

    path("customers/delete/<int:id>/",views.delete_customer,name="delete_customer"),


    # PRODUCTS

    path("products/", views.product_list, name="product_list"),

    path("products/add/", views.add_product, name="add_product"),

    path("products/edit/<int:id>/",views.edit_product,name="edit_product"),

    path("products/delete/<int:id>/",views.delete_product,name="delete_product"),


    # ORDERS

    path("orders/", views.order_page, name="order_page"),

    path("orders/multicolor/", views.multicolor_order_page, name="multicolor_order_page"),

    path("orders/services/", views.order_page, {"mode": "services"}, name="configured_service_order"),

    path("customers/search/", views.search_customer, name="search_customer"),

    path("products/search/", views.search_product, name="search_product"),

    path("billing/", views.billing_page, name="billing_page"),

    path(
        "multicolor-billing/",
        views.multicolor_billing_page,
        name="multicolor_billing_page",
    ),

    path("invoice/",views.invoice_page,name="invoice_page"),

    path("invoice/view/<int:id>/", views.view_invoice, name="view_invoice"),

    path("invoice/save/",views.save_invoice,name="save_invoice"),

    path(
    "customers/save-new/",
    views.save_new_customer,
    name="save_new_customer"
),

    path("logout/",views.logoutpage,name="logoutpage"),

]
