from django.contrib.auth import views as auth_views
from django.urls import path

from . import catalog, views

urlpatterns = [
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
]
