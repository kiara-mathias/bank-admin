from django.urls import path
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from . import views

urlpatterns = [
    # Custom Login
    path('', views.custom_login, name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),

    path('users_list/', views.user_list, name='user_list'), 
    # User URLs
    # path('', views.user_list, name='user_list'),
    path('create/', login_required(views.user_create), name='user_create'),
    path('update/<int:pk>/', login_required(views.user_update), name='user_update'),
    path('delete/<int:pk>/', login_required(views.user_delete), name='user_delete'),

    # account + kyc status
    path('account/<int:account_id>/update-status/', login_required(views.update_account_status), name='update_account_status'),
    path('account/<int:account_id>/update-kyc/', login_required(views.update_kyc_status), name='update_kyc_status'),

    # Account URLs
    path('accounts/', login_required(views.account_info_list), name='account_info_list'),
    path('accounts/create/', login_required(views.account_info_create), name='account_info_create'),
    path('accounts/update/<int:pk>/', login_required(views.account_info_update), name='account_info_update'),
    path('accounts/delete/<int:pk>/', login_required(views.account_info_delete), name='account_info_delete'),

   # user specific account info
    path('users/<int:user_id>/accounts/', login_required(views.user_account_info), name='user_account_info'),
    path('users/<int:user_id>/make_transaction/', login_required(views.make_transaction), name='make_transaction'),

    
    # employee 
    path('employees/', login_required(views.employee_list), name='employee_list'),
    path('employee/create/', login_required(views.employee_create), name='employee_create'),
    path('employees/<int:pk>/update/', login_required(views.employee_update), name='employee_update'),
    path('employees/<int:pk>/freeze/', login_required(views.employee_freeze), name='employee_freeze'),
    path('employees/<int:pk>/unfreeze/', login_required(views.employee_unfreeze), name='employee_unfreeze'),
    

    #search function
    path('users/live-search/', login_required(views.live_user_search), name='live_user_search'),
    path('employees/live-search/', login_required(views.employee_live_search), name='employee_live_search'),

    # PDF download
    path('users/<int:user_id>/download_pdf/', login_required(views.download_account_pdf), name='download_account_pdf'),
]
