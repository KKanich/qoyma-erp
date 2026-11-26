from django.contrib.auth import views as auth_views
from django.urls import path

from . import catalog, guide, inventory, phone_scanner, views

urlpatterns = [
    path('scanner/sessions/', phone_scanner.create_session, name='scanner_create'),
    path('scanner/<uuid:session_id>/', phone_scanner.phone_page, name='scanner_phone'),
    path('scanner/<uuid:session_id>/qr/', phone_scanner.qr_code, name='scanner_qr'),
    path('scanner/<uuid:session_id>/poll/', phone_scanner.poll, name='scanner_poll'),
    path('scanner/<uuid:session_id>/scan/', phone_scanner.submit_scan, name='scanner_submit'),
    path('scanner/<uuid:session_id>/ack/', phone_scanner.acknowledge, name='scanner_ack'),
    path('scanner/<uuid:session_id>/close/', phone_scanner.close_session, name='scanner_close'),
    path('scanner/<uuid:session_id>/events/<int:event_id>/', phone_scanner.event_status, name='scanner_event'),
    path('products/<int:pk>/adjust/', inventory.adjust_stock, name='adjust_stock'),
    path('inventory/audit/', inventory.inventory_audit, name='inventory_audit'),
    path('inventory/audit/xlsx/', inventory.inventory_xlsx, name='inventory_xlsx'),
    path('products/', catalog.product_list, name='product_list'),
    path('products/new/', catalog.product_edit, name='product_create'),
    path('products/<int:pk>/edit/', catalog.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', catalog.product_delete, name='product_delete'),
    path('', views.pos_page, name='pos_page'),
    path('login/', auth_views.LoginView.as_view(template_name='store/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('api/checkout/', views.pos_checkout, name='pos_checkout'),
    path('api/alerts/', views.dashboard_alerts, name='dashboard_alerts'),
    path('api/stock-receipt/', views.stock_receipt_api, name='stock_receipt'),
    path('receive/', views.receive_page, name='receive_page'),
    path('report/', views.report_page, name='report_page'),
    path('report/csv/', views.report_csv, name='report_csv'),
    path('report/xlsx/', views.report_xlsx, name='report_xlsx'),
    path('help/', guide.help_page, name='help_page'),
]
