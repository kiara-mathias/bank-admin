import time
import logging
from datetime import datetime, timedelta
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q, Sum
from django.db import models
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from decimal import Decimal
from xhtml2pdf import pisa
from django.conf import settings

logger = logging.getLogger(__name__)

from .models import (
    UsersNew, Account, Transaction, Employee, TransactionRequest,
    TRANSACTION_LIMIT_PER_TXN, TRANSACTION_LIMIT_PER_DAY
)
from .forms import UsersNewForm, AccountInfoForm, TransactionForm, EmployeeForm, EmployeeCreationForm


# ========== PERMISSION HELPERS ==========

def is_manager(user):
    """Check if user is a manager (Employee HR)"""
    return user.groups.filter(name='Manager').exists() or user.is_superuser

def is_supervisor(user):
    """Check if user is a supervisor (Bank Manager)"""
    return user.groups.filter(name='Supervisor').exists() or user.is_superuser

def is_clerk(user):
    """Check if user is a clerk (Bank Teller - Read Only)"""
    return user.groups.filter(name='Clerk').exists() or user.is_superuser

def can_manage_employees(user):
    """Only Managers can manage employees"""
    return is_manager(user)

def can_view_customers(user):
    """Supervisors and Clerks can view customers (Managers too, optionally)"""
    if user.is_superuser: return True
    return user.groups.filter(name__in=['Supervisor', 'Clerk']).exists()

def can_manage_customers(user):
    """Only Supervisors can create/edit customers"""
    if user.is_superuser: return True
    return user.groups.filter(name='Supervisor').exists()

def can_make_transactions(user):
    """Supervisors AND Clerks can make transactions"""
    if user.is_superuser: return True
    return user.groups.filter(name__in=['Supervisor', 'Clerk']).exists()


# ========== AUTHENTICATION VIEWS ==========

def get_user_role(request):
    """AJAX endpoint to fetch user's assigned role based on username"""
    username = request.GET.get('username', '').strip()
    
    if not username:
        return JsonResponse({'role': None})
    
    # First check if it's a Django User (Employee)
    try:
        user = User.objects.get(username=username)
        
        # Superusers can choose any role, so don't auto-fill
        if user.is_superuser:
            return JsonResponse({'role': None, 'is_superuser': True})
        
        # Get the user's first assigned group (role)
        group = user.groups.first()
        if group:
            return JsonResponse({'role': group.name})
        else:
            return JsonResponse({'role': None})
            
    except User.DoesNotExist:
        pass
    
    # Check if it's a Customer (UsersNew)
    try:
        customer = UsersNew.objects.get(username=username)
        return JsonResponse({'role': 'Customer'})
    except UsersNew.DoesNotExist:
        pass
    
    return JsonResponse({'role': None})


def custom_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        # ========== CUSTOMER LOGIN ==========
        if role == 'Customer':
            try:
                customer = UsersNew.objects.get(username=username)
                
                # Check password (plain text comparison for customers)
                if customer.password == password:
                    # Store customer info in session
                    request.session['customer_id'] = customer.emp_id
                    request.session['customer_username'] = customer.username
                    request.session['is_customer'] = True
                    print(f"[TIMING] Customer '{username}' logged in successfully")
                    return redirect('customer_dashboard')
                else:
                    messages.error(request, "Invalid username or password.")
                    return render(request, 'users/login.html')
                    
            except UsersNew.DoesNotExist:
                messages.error(request, "Invalid username or password.")
                return render(request, 'users/login.html')

        # ========== EMPLOYEE LOGIN (Manager/Supervisor/Clerk) ==========
        # TIMING: Track authentication performance
        start_time = time.time()
        user = authenticate(request, username=username, password=password)
        auth_time = time.time() - start_time
        
        # Debug: Show which hasher was used
        if user:
            current_hasher = user.password.split('$')[0] if '$' in user.password else 'unknown'
            print(f"[TIMING] authenticate() took {auth_time:.2f}s for user '{username}' (hasher: {current_hasher})")
            
            # Force password upgrade to MD5 if still using slow hasher
            if current_hasher.startswith('pbkdf2') and auth_time > 1.0:
                print(f"[TIMING] Upgrading password from {current_hasher} to MD5...")
                user.set_password(password)
                user.save(update_fields=['password'])
                new_hasher = user.password.split('$')[0]
                print(f"[TIMING] Password upgraded to {new_hasher}")
        else:
            print(f"[TIMING] authenticate() took {auth_time:.2f}s for user '{username}' (FAILED)")
        
        if user is not None:
            # Fetch all user groups in ONE query (optimization: avoids multiple DB hits)
            user_groups = set(user.groups.values_list('name', flat=True))
            
            # Check if user has the selected role
            if role:
                # If user is SUPERUSER, they can log in as ANY role (Admin/Manager/Supervisor/Clerk)
                # If user is NORMAL, they must have the specific group assigned
                if not user.is_superuser:
                    if role not in user_groups:
                        messages.error(request, "Invalid details. You are not assigned this role.")
                        return render(request, 'users/login.html')
            
            if user.is_active:
                login_start = time.time()
                login(request, user)
                login_time = time.time() - login_start
                print(f"[TIMING] login() took {login_time:.2f}s")
                
                # Clear any customer session data
                request.session.pop('customer_id', None)
                request.session.pop('customer_username', None)
                request.session.pop('is_customer', None)
                
                # Redirect based on role
                # Superuser -> Employee List by default (Manager View) or User List if they chose Supervisor/Clerk
                if user.is_superuser:
                    if role == 'Supervisor' or role == 'Clerk':
                        return redirect('user_list')
                    return redirect('employee_list') # Default for Admin/Manager selection

                # Use cached groups instead of multiple DB queries
                if 'Manager' in user_groups:
                    return redirect('employee_list')
                elif 'Supervisor' in user_groups or 'Clerk' in user_groups:
                    return redirect('user_list')
                else:
                    return redirect('user_list')
            else:
                messages.error(request, "Your account is disabled.")
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'users/login.html')


# ========== EMPLOYEE VIEWS (Manager Only) ==========

@login_required
@user_passes_test(can_manage_employees)
def employee_list(request):
    """List all employees - Manager Only"""
    employees_qs = Employee.objects.select_related('user', 'role').all()

    # Search functionality
    query = request.GET.get('q', '').strip()
    if query:
        employees_qs = employees_qs.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(contact__icontains=query)
        )

    # Filter by status
    status_filter = request.GET.get('status')
    if status_filter in ['ACTIVE', 'FROZEN']:
        employees_qs = employees_qs.filter(status=status_filter)

    # Filter by role
    role_filter = request.GET.get('role')
    if role_filter:
        employees_qs = employees_qs.filter(role__name=role_filter)

    # Filter by joining date
    filter_value = request.GET.get('filter')
    today = timezone.now().date()
    if filter_value == '3months':
        employees_qs = employees_qs.filter(joining_date__gte=today - timedelta(days=90))
    elif filter_value == '6months':
        employees_qs = employees_qs.filter(joining_date__gte=today - timedelta(days=180))
    elif filter_value == '1year':
        employees_qs = employees_qs.filter(joining_date__gte=today - timedelta(days=365))

    employees_qs = employees_qs.order_by('-joining_date')

    # Pagination
    paginator = Paginator(employees_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    available_roles = Group.objects.all()

    return render(request, 'users/employee_list.html', {
        'page_obj': page_obj,
        'employees': page_obj,
        'query': query,
        'status_filter': status_filter,
        'role_filter': role_filter,
        'filter_value': filter_value,
        'available_roles': available_roles,
        'is_manager': True, 
    })


@login_required
@user_passes_test(can_manage_employees)
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeCreationForm(request.POST)
        if form.is_valid():
            try:
                # TIMING: Track employee creation performance
                start_time = time.time()
                employee = form.save()
                save_time = time.time() - start_time
                print(f"[TIMING] Employee creation (form.save()) took {save_time:.2f}s")
                messages.success(request, f"Employee '{employee.username}' created successfully.")
                return redirect('employee_list')
            except IntegrityError:
                messages.error(request, "Could not create employee. Possible duplicate data.")
        else:
             messages.error(request, "Please correct the errors below.")
    else:
        form = EmployeeCreationForm()

    return render(request, 'users/employee_create.html', {
        'title': 'Register Employee',
        'form': form
    })

@login_required
@user_passes_test(can_manage_employees)
def employee_update(request, pk):
    """Update employee info - Manager Only"""
    emp = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        form = EmployeeForm(request.POST, instance=emp)
        if form.is_valid():
            emp = form.save(commit=False)
            emp.save()

            # Update linked User
            if emp.user:
                emp.user.username = emp.email
                emp.user.email = emp.email
                new_password = form.cleaned_data.get('password')
                if new_password:
                    emp.user.set_password(new_password)

                role = form.cleaned_data.get('role')
                if role:
                    emp.user.groups.clear()
                    emp.user.groups.add(role)
                
                emp.user.save()

            messages.success(request, f"Employee '{emp.username}' updated successfully!")
            return redirect('employee_list')
    else:
        form = EmployeeForm(instance=emp)

    return render(request, 'users/employee_form.html', {
        'form': form,
        'title': 'Update Employee',
        'employee': emp,
    })


@login_required
@user_passes_test(can_manage_employees)
def employee_delete(request, pk):
    """Delete employee - Manager Only"""
    emp = get_object_or_404(Employee, pk=pk)

    if request.method == 'POST':
        username = emp.username
        if emp.user:
            emp.user.delete()
        emp.delete()
        messages.success(request, f"Employee '{username}' deleted successfully!")
        return redirect('employee_list')

    return render(request, 'users/employee_confirm_delete.html', {'employee': emp})


@login_required
@user_passes_test(can_manage_employees)
def employee_freeze(request, pk):
    """Freeze employee - Manager Only"""
    emp = get_object_or_404(Employee, pk=pk)

    if emp.status == 'FROZEN':
        messages.warning(request, "Employee is already frozen.")
    else:
        emp.status = 'FROZEN'
        emp.save()
        if emp.user:
            emp.user.is_active = False
            emp.user.save()
        messages.success(request, f"Employee '{emp.username}' has been frozen.")

    return redirect('employee_list')


@login_required
@user_passes_test(can_manage_employees)
def employee_unfreeze(request, pk):
    """Unfreeze employee - Manager Only"""
    emp = get_object_or_404(Employee, pk=pk)

    if emp.status == 'ACTIVE':
        messages.info(request, "Employee is already active.")
    else:
        emp.status = 'ACTIVE'
        emp.save()
        if emp.user:
            emp.user.is_active = True
            emp.user.save()
        messages.success(request, f"Employee '{emp.username}' has been reactivated.")

    return redirect('employee_list')


@login_required
@user_passes_test(can_manage_employees)
def employee_live_search(request):
    """AJAX endpoint for live employee search"""
    query = request.GET.get('q', '').strip()
    results = []

    employees = Employee.objects.select_related('role').order_by('-joining_date')
    
    if query:
        employees = employees.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(contact__icontains=query)
        )[:50]
    else:
        employees = employees[:50]

    for emp in employees:
        results.append({
            "id": emp.id,
            "username": emp.username,
            "email": emp.email,
            "contact": emp.contact,
            "joining_date": emp.joining_date.strftime("%d %b, %Y") if emp.joining_date else '',
            "status": emp.status,
            "role": emp.role.name if emp.role else 'No Role'
        })

    return JsonResponse({"results": results})





# ========== USER VIEWS (Supervisor & Clerk) ==========

@login_required
def live_user_search(request):
    """AJAX endpoint for live user search"""
    # Allow Managers to search too if they land here, but UI hides it
    if not (can_view_customers(request.user) or can_manage_employees(request.user)):
        return JsonResponse({'results': []})

    query = request.GET.get('q', '').strip()
    users = UsersNew.objects.select_related('account')

    if query:
        q_objects = (
            Q(username__icontains=query) |
            Q(email__icontains=query)
        )
        if query.isdigit():
            q_objects |= Q(contact__icontains=query) | Q(account__account_no__icontains=query)
        
        users = users.filter(q_objects).distinct()

    # Pass the users to the template for server-side rendering
    return render(request, 'users/partials/user_table_rows.html', {
        'page_obj': users,
        'is_supervisor': can_manage_customers(request.user),
        'is_clerk': is_clerk(request.user),
    })


@login_required
@user_passes_test(can_view_customers)
def user_list(request):
    """List all bank users - Supervisor & Clerk"""
    query = request.GET.get('q')
    users = UsersNew.objects.select_related('account').all()
    filter_value = request.GET.get('filter')
    users = users.order_by('username')
    
    if query:
        users = users.filter(username__icontains=query)

    today = timezone.now().date()

    if filter_value == '3months':
        users = users.filter(joining_date__gte=today - timedelta(days=90))
    elif filter_value == '6months':
        users = users.filter(joining_date__gte=today - timedelta(days=180))
    elif filter_value == '1year':
        users = users.filter(joining_date__gte=today - timedelta(days=365))
    
    # Pagination
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'users/user_list.html', {
        'page_obj': page_obj,
        'query': query,
        'is_supervisor': can_manage_customers(request.user), # For UI logic
        'is_clerk': is_clerk(request.user),
        'is_manager': can_manage_employees(request.user), # For Employee Link
    })


@login_required
@user_passes_test(can_manage_customers)
def user_create(request):
    """Create a new bank user - Supervisor Only"""
    if request.method == 'POST':
        form = UsersNewForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Create account for the user
            Account.objects.create(
                user=user,
                current_balance=Decimal('500.00')
            )

            messages.success(request, 'User and account created successfully!')
            return redirect('user_list')
    else:
        form = UsersNewForm()

    return render(request, 'users/user_form.html', {
        'form': form,
        'title': 'Create User'
    })


@login_required
@user_passes_test(can_manage_customers)
def user_update(request, pk):
    """Update bank user information - Supervisor Only"""
    user = get_object_or_404(UsersNew, pk=pk)

    if request.method == 'POST':
        form = UsersNewForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'User updated successfully!')
            return redirect('user_list')
    else:
        form = UsersNewForm(instance=user)

    return render(request, 'users/user_form.html', {
        'form': form,
        'title': 'Update User'
    })


@login_required
@user_passes_test(can_manage_customers)
def user_delete(request, pk):
    """Delete bank user - Supervisor Only"""
    user = get_object_or_404(UsersNew, pk=pk)

    if request.method == 'POST':
        Account.objects.filter(user=user).delete()
        user.delete()
        messages.success(request, 'User deleted successfully!')
        return redirect('user_list')

    return render(request, 'users/user_confirm_delete.html', {'user': user})


# ========== TRANSACTION VIEWS ==========

def filter_transactions(transactions, filter_value=None, start_date_str=None, end_date_str=None):
    """Filter transactions by date range"""
    today = timezone.now()

    if filter_value == 'this_month':
        start_date = today.replace(day=1)
        return transactions.filter(txn_datetime__gte=start_date)
    elif filter_value == '3months':
        return transactions.filter(txn_datetime__gte=today - timedelta(days=90))
    elif filter_value == '6months':
        return transactions.filter(txn_datetime__gte=today - timedelta(days=180))
    elif filter_value == '1year':
        return transactions.filter(txn_datetime__gte=today - timedelta(days=365))
    elif filter_value == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            end_date = end_date.replace(hour=23, minute=59, second=59)
            return transactions.filter(txn_datetime__range=(start_date, end_date))
        except ValueError:
            return transactions

    return transactions


@login_required
@user_passes_test(can_make_transactions)
def make_transaction(request, user_id):
    """
    Process deposit or withdrawal - Supervisor & Clerk
    
    Control Flow:
    1. Check account status (must be ACTIVE)
    2. Check KYC status (must be VERIFIED)
    3. For withdrawals, check sufficient balance
    4. Check transaction limits:
       - Per transaction: ₹10,000
       - Per day: ₹50,000
    5. Auto-approve if within limits, else create pending request
    """
    user = get_object_or_404(UsersNew, pk=user_id)
    account, created = Account.objects.get_or_create(
        user=user,
        defaults={'current_balance': Decimal('500.00')}
    )
    current_balance = account.current_balance

    # Mark all messages as used
    storage = messages.get_messages(request)
    for _ in storage:
        pass

    # ========== PRE-TRANSACTION CHECKS ==========
    # 1. Check account status
    if account.account_status != 'ACTIVE':
        messages.error(request, f'Transaction blocked: Account is {account.get_account_status_display()}.')
        return redirect('user_account_info', user_id=user.pk)
    
    # 2. Check KYC status
    if account.kyc_status != 'VERIFIED':
        messages.error(request, f'Transaction blocked: KYC is {account.get_kyc_status_display()}. Please complete KYC verification first.')
        return redirect('user_account_info', user_id=user.pk)

    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            txn_type = form.cleaned_data['txn_type']
            amount = form.cleaned_data['amount']
            description = form.cleaned_data.get('description', '')
            
            # 3. For withdrawals, check sufficient balance
            if txn_type == 'withdraw':
                if amount > account.current_balance:
                    messages.error(request, 'Insufficient balance for this withdrawal.')
                    return redirect('make_transaction', user_id=user.pk)
            
            # 4. Check transaction limits
            daily_total = TransactionRequest.get_daily_total(account)
            exceeds_per_txn = amount > TRANSACTION_LIMIT_PER_TXN
            exceeds_daily = (daily_total + amount) > TRANSACTION_LIMIT_PER_DAY
            
            # 5. Decide: Auto-approve or Pending
            if exceeds_per_txn or exceeds_daily:
                # ========== PENDING REQUEST (needs approval) ==========
                reason = []
                if exceeds_per_txn:
                    reason.append(f'exceeds per-transaction limit of ₹{TRANSACTION_LIMIT_PER_TXN:,.2f}')
                if exceeds_daily:
                    reason.append(f'exceeds daily limit of ₹{TRANSACTION_LIMIT_PER_DAY:,.2f}')
                
                # Create pending request
                TransactionRequest.objects.create(
                    account=account,
                    txn_type=txn_type,
                    amount=amount,
                    description=description,
                    status='PENDING'
                )
                
                messages.warning(
                    request, 
                    f'Transaction of ₹{amount:,.2f} requires approval ({", ".join(reason)}). '
                    f'Request submitted for review.'
                )
                return redirect('user_account_info', user_id=user.pk)
            
            else:
                # ========== AUTO-APPROVED (within limits) ==========
                if txn_type == 'withdraw':
                    new_balance = account.current_balance - amount
                else:  # deposit
                    new_balance = account.current_balance + amount

                account.current_balance = new_balance
                account.save()
                
                txn = Transaction(
                    account=account,
                    current_balance=new_balance,
                    txn_type=txn_type,
                    amount=amount,
                    description=description
                )
                txn.save()
                
                messages.success(request, f'Transaction of ₹{amount:,.2f} completed successfully!')
                return redirect('user_account_info', user_id=user.pk)
    else:
        form = TransactionForm()

    # Get pending requests count for this account
    pending_requests = TransactionRequest.objects.filter(account=account, status='PENDING').count()
    daily_total = TransactionRequest.get_daily_total(account)

    return render(request, 'users/transaction_form.html', {
        'form': form,
        'user': user,
        'account': account,
        'current_balance': current_balance,
        'pending_requests': pending_requests,
        'daily_total': daily_total,
        'limit_per_txn': TRANSACTION_LIMIT_PER_TXN,
        'limit_per_day': TRANSACTION_LIMIT_PER_DAY,
    })


# ========== TRANSACTION REQUEST APPROVAL VIEWS (Staff Only) ==========

@login_required
@user_passes_test(can_make_transactions)
def pending_transaction_list(request):
    """List all pending transaction requests - Supervisor & Clerk can view and approve"""
    pending_requests = TransactionRequest.objects.filter(status='PENDING').select_related('account', 'account__user').order_by('-requested_at')
    
    # Filter by account if specified
    account_filter = request.GET.get('account')
    if account_filter:
        pending_requests = pending_requests.filter(account__account_no=account_filter)
    
    # Get counts for dashboard
    total_pending = pending_requests.count()
    total_amount_pending = pending_requests.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
    
    return render(request, 'users/pending_transactions.html', {
        'pending_requests': pending_requests,
        'total_pending': total_pending,
        'total_amount_pending': total_amount_pending,
        'limit_per_txn': TRANSACTION_LIMIT_PER_TXN,
        'limit_per_day': TRANSACTION_LIMIT_PER_DAY,
    })


@login_required
@user_passes_test(can_make_transactions)
def approve_transaction(request, request_id):
    """Approve a pending transaction request"""
    txn_request = get_object_or_404(TransactionRequest, pk=request_id, status='PENDING')
    account = txn_request.account
    
    # Re-validate before approval
    # 1. Check account status
    if account.account_status != 'ACTIVE':
        messages.error(request, f'Cannot approve: Account is {account.get_account_status_display()}.')
        return redirect('pending_transaction_list')
    
    # 2. Check KYC status
    if account.kyc_status != 'VERIFIED':
        messages.error(request, f'Cannot approve: KYC is {account.get_kyc_status_display()}.')
        return redirect('pending_transaction_list')
    
    # 3. For withdrawals, re-check balance
    if txn_request.txn_type == 'withdraw':
        if txn_request.amount > account.current_balance:
            messages.error(request, f'Cannot approve: Insufficient balance. Current balance: ₹{account.current_balance:,.2f}')
            return redirect('pending_transaction_list')
    
    # Process the transaction
    if txn_request.txn_type == 'withdraw':
        new_balance = account.current_balance - txn_request.amount
    else:  # deposit
        new_balance = account.current_balance + txn_request.amount
    
    # Update account balance
    account.current_balance = new_balance
    account.save()
    
    # Create the actual transaction
    txn = Transaction.objects.create(
        account=account,
        current_balance=new_balance,
        txn_type=txn_request.txn_type,
        amount=txn_request.amount,
        description=txn_request.description or f'Approved by {request.user.username}'
    )
    
    # Update the request status
    txn_request.status = 'APPROVED'
    txn_request.reviewed_by = request.user
    txn_request.reviewed_at = timezone.now()
    txn_request.transaction = txn
    txn_request.save()
    
    messages.success(
        request, 
        f'Transaction approved: {txn_request.txn_type.title()} of ₹{txn_request.amount:,.2f} for account {account.account_no}'
    )
    return redirect('pending_transaction_list')


@login_required
@user_passes_test(can_make_transactions)
def reject_transaction(request, request_id):
    """Reject a pending transaction request"""
    txn_request = get_object_or_404(TransactionRequest, pk=request_id, status='PENDING')
    
    if request.method == 'POST':
        rejection_reason = request.POST.get('rejection_reason', '').strip()
        
        txn_request.status = 'REJECTED'
        txn_request.reviewed_by = request.user
        txn_request.reviewed_at = timezone.now()
        txn_request.rejection_reason = rejection_reason or 'No reason provided'
        txn_request.save()
        
        messages.success(
            request, 
            f'Transaction rejected: {txn_request.txn_type.title()} of ₹{txn_request.amount:,.2f} for account {txn_request.account.account_no}'
        )
        return redirect('pending_transaction_list')
    
    return render(request, 'users/reject_transaction.html', {
        'txn_request': txn_request
    })


# ========== ACCOUNT INFO VIEWS ==========

@login_required
@user_passes_test(can_view_customers)
def account_info_list(request):
    """List all accounts - Supervisor & Clerk"""
    query = request.GET.get('q')
    accounts = Account.objects.select_related('user')

    if query:
        q_objects = Q(user__username__icontains=query) | Q(user__email__icontains=query)
        if query.isdigit():
            q_objects |= Q(account_no=int(query))
        accounts = accounts.filter(q_objects)

    return render(request, 'users/account_info_list.html', {
        'accounts': accounts
    })


@login_required
@user_passes_test(can_manage_customers)
def account_info_create(request):
    """Create a new account - Supervisor Only"""
    if request.method == 'POST':
        form = AccountInfoForm(request.POST)
        if form.is_valid():
            account = Account(
                user=form.cleaned_data['emp'],
                current_balance=form.cleaned_data.get('current_bal', Decimal('0.00'))
            )
            account.save()
            messages.success(request, 'Account created successfully!')
            return redirect('account_info_list')
    else:
        form = AccountInfoForm()

    return render(request, 'users/account_info_form.html', {
        'form': form,
        'title': 'Create Account'
    })


@login_required
@user_passes_test(can_manage_customers)
def account_info_update(request, pk):
    """Update account information - Supervisor Only"""
    account = get_object_or_404(Account, pk=pk)

    if request.method == 'POST':
        form = AccountInfoForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Account updated successfully!')
            return redirect('account_info_list')
    else:
        form = AccountInfoForm(instance=account)

    return render(request, 'users/account_info_form.html', {
        'form': form,
        'title': 'Update Account'
    })


@login_required
@user_passes_test(can_manage_customers)
def account_info_delete(request, pk):
    """Delete an account - Supervisor Only"""
    account = get_object_or_404(Account, pk=pk)

    if request.method == 'POST':
        account.delete()
        messages.success(request, 'Account deleted successfully!')
        return redirect('account_info_list')

    return render(request, 'users/account_info_confirm_delete.html', {
        'account': account
    })


@login_required
@user_passes_test(can_view_customers)
def user_account_info(request, user_id):
    """View detailed account info - Supervisor & Clerk"""
    user = get_object_or_404(UsersNew, pk=user_id)
    account, created = Account.objects.get_or_create(
        user=user,
        defaults={'current_balance': 500}
    )

    filter_value = request.GET.get('filter')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    transactions = Transaction.objects.filter(account=account).order_by('-txn_datetime')
    transactions = filter_transactions(transactions, filter_value, start_date, end_date)

    return render(request, 'users/user_account_info.html', {
        'user': user,
        'account': account,
        'transactions': transactions,
        'filter_value': filter_value,
        'start_date': start_date,
        'end_date': end_date,
        'is_supervisor': can_make_transactions(request.user), # To show/hide 'Make Transaction' button (Supervisor & Clerk)
        'is_customer': False,  # Staff view, not customer
    })


@login_required
@user_passes_test(can_view_customers)
def download_account_pdf(request, user_id):
    """Generate PDF - Supervisor & Clerk"""
    user = get_object_or_404(UsersNew, pk=user_id)
    account, created = Account.objects.get_or_create(
        user=user,
        defaults={'current_balance': 500}
    )

    filter_value = request.GET.get('filter')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    transactions = Transaction.objects.filter(account=account).order_by('txn_datetime')
    transactions = filter_transactions(transactions, filter_value, start_date, end_date)

    template_path = 'users/user_account_info_pdf.html'
    context = {
        'user': user,
        'account': account,
        'transactions': transactions,
        'filter_value': filter_value,
        'start_date': start_date,
        'end_date': end_date,
    }

    html = get_template(template_path).render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Account_Statement_{user.username}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error <pre>' + html + '</pre>')

    return response


@login_required
@user_passes_test(can_manage_customers)
def update_account_status(request, account_id):
    """Update account status - Supervisor Only"""
    account = get_object_or_404(Account, id=account_id)
    new_status = request.POST.get('account_status')

    # Validate choice
    valid_statuses = dict(Account.STATUS_CHOICES)
    if new_status in valid_statuses:
        account.account_status = new_status
        account.save()
        messages.success(request, f'Account status updated to {new_status}')

    return redirect('user_list')


@login_required
@user_passes_test(can_manage_customers)
def update_kyc_status(request, account_id):
    """Update KYC status - Supervisor Only"""
    account = get_object_or_404(Account, id=account_id)
    new_kyc_status = request.POST.get('kyc_status')

    # Validate choice
    valid_kyc_statuses = dict(Account.KYC_CHOICES)
    if new_kyc_status in valid_kyc_statuses:
        account.kyc_status = new_kyc_status
        account.save()
        messages.success(request, f'KYC status updated to {new_kyc_status}')

    return redirect('user_list')


# ========== CUSTOMER VIEWS ==========

def customer_login_required(view_func):
    """Decorator to check if customer is logged in via session"""
    def wrapper(request, *args, **kwargs):
        if not request.session.get('is_customer'):
            messages.error(request, "Please login as a customer to access this page.")
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


@customer_login_required
def customer_dashboard(request):
    """Customer dashboard - shows their own account and transactions (reuses staff template)"""
    customer_id = request.session.get('customer_id')
    
    if not customer_id:
        messages.error(request, "Session expired. Please login again.")
        return redirect('login')
    
    try:
        customer = UsersNew.objects.get(emp_id=customer_id)
    except UsersNew.DoesNotExist:
        messages.error(request, "Customer not found. Please login again.")
        request.session.flush()
        return redirect('login')
    
    # Get or create account for the customer
    account, created = Account.objects.get_or_create(
        user=customer,
        defaults={'current_balance': Decimal('500.00')}
    )
    
    # Get filter parameters
    filter_value = request.GET.get('filter')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    # Get transactions
    transactions = Transaction.objects.filter(account=account).order_by('-txn_datetime')
    transactions = filter_transactions(transactions, filter_value, start_date, end_date)
    
    # Get pending transaction requests for this customer
    pending_requests = TransactionRequest.objects.filter(
        account=account, 
        status='PENDING'
    ).order_by('-requested_at')
    
    # Get rejected requests (recent ones)
    rejected_requests = TransactionRequest.objects.filter(
        account=account,
        status='REJECTED'
    ).order_by('-reviewed_at')[:5]
    
    # Reuse the SAME template as staff, but with customer context
    return render(request, 'users/user_account_info.html', {
        'user': customer,  # Same variable name as staff view
        'account': account,
        'transactions': transactions,
        'filter_value': filter_value,
        'start_date': start_date,
        'end_date': end_date,
        'is_customer': True,  # Flag to hide staff-only features in template
        'is_supervisor': False,  # Customer can't make transactions
        'pending_requests': pending_requests,
        'rejected_requests': rejected_requests,
    })


@customer_login_required
def customer_request_transaction(request):
    """
    Customer transaction - same control flow as staff:
    - Within limits (₹10,000/txn, ₹50,000/day): Auto-approved
    - Exceeds limits: Requires staff approval
    """
    customer_id = request.session.get('customer_id')
    
    if not customer_id:
        messages.error(request, "Session expired. Please login again.")
        return redirect('login')
    
    try:
        customer = UsersNew.objects.get(emp_id=customer_id)
    except UsersNew.DoesNotExist:
        messages.error(request, "Customer not found. Please login again.")
        request.session.flush()
        return redirect('login')
    
    account, created = Account.objects.get_or_create(
        user=customer,
        defaults={'current_balance': Decimal('500.00')}
    )
    
    # ========== PRE-REQUEST CHECKS ==========
    # 1. Check account status
    if account.account_status != 'ACTIVE':
        messages.error(request, f'Transaction blocked: Your account is {account.get_account_status_display()}.')
        return redirect('customer_dashboard')
    
    # 2. Check KYC status
    if account.kyc_status != 'VERIFIED':
        messages.error(request, f'Transaction blocked: Your KYC is {account.get_kyc_status_display()}. Please complete KYC verification first.')
        return redirect('customer_dashboard')
    
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            txn_type = form.cleaned_data['txn_type']
            amount = form.cleaned_data['amount']
            description = form.cleaned_data.get('description', '')
            
            # 3. For withdrawals, check sufficient balance
            if txn_type == 'withdraw':
                if amount > account.current_balance:
                    messages.error(request, 'Insufficient balance for this withdrawal.')
                    return redirect('customer_request_transaction')
            
            # 4. Check transaction limits
            daily_total = TransactionRequest.get_daily_total(account)
            exceeds_per_txn = amount > TRANSACTION_LIMIT_PER_TXN
            exceeds_daily = (daily_total + amount) > TRANSACTION_LIMIT_PER_DAY
            
            # 5. Decide: Auto-approve or Pending
            if exceeds_per_txn or exceeds_daily:
                # ========== PENDING REQUEST (needs approval) ==========
                reason = []
                if exceeds_per_txn:
                    reason.append(f'exceeds ₹{TRANSACTION_LIMIT_PER_TXN:,.0f} per transaction limit')
                if exceeds_daily:
                    reason.append(f'exceeds ₹{TRANSACTION_LIMIT_PER_DAY:,.0f} daily limit')
                
                TransactionRequest.objects.create(
                    account=account,
                    txn_type=txn_type,
                    amount=amount,
                    description=description,
                    status='PENDING'
                )
                
                messages.warning(
                    request, 
                    f'Your {txn_type} of ₹{amount:,.2f} requires approval ({", ".join(reason)}). '
                    f'You will be notified once reviewed.'
                )
                return redirect('customer_dashboard')
            
            else:
                # ========== AUTO-APPROVED (within limits) ==========
                if txn_type == 'withdraw':
                    new_balance = account.current_balance - amount
                else:  # deposit
                    new_balance = account.current_balance + amount

                account.current_balance = new_balance
                account.save()
                
                txn = Transaction.objects.create(
                    account=account,
                    current_balance=new_balance,
                    txn_type=txn_type,
                    amount=amount,
                    description=description or 'Self-service transaction'
                )
                
                messages.success(request, f'Transaction successful! ₹{amount:,.2f} {txn_type} completed.')
                return redirect('customer_dashboard')
    else:
        form = TransactionForm()
    
    # Get pending requests count and daily total
    pending_count = TransactionRequest.objects.filter(account=account, status='PENDING').count()
    daily_total = TransactionRequest.get_daily_total(account)
    
    return render(request, 'users/customer_transaction_request.html', {
        'form': form,
        'customer': customer,
        'account': account,
        'pending_count': pending_count,
        'daily_total': daily_total,
        'limit_per_txn': TRANSACTION_LIMIT_PER_TXN,
        'limit_per_day': TRANSACTION_LIMIT_PER_DAY,
    })


@customer_login_required
def customer_download_pdf(request):
    """Generate PDF statement for customer - reuses SAME template as staff"""
    customer_id = request.session.get('customer_id')
    
    if not customer_id:
        return redirect('login')
    
    try:
        customer = UsersNew.objects.get(emp_id=customer_id)
    except UsersNew.DoesNotExist:
        return redirect('login')
    
    account, created = Account.objects.get_or_create(
        user=customer,
        defaults={'current_balance': Decimal('500.00')}
    )
    
    filter_value = request.GET.get('filter')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    transactions = Transaction.objects.filter(account=account).order_by('txn_datetime')
    transactions = filter_transactions(transactions, filter_value, start_date, end_date)
    
    # Reuse SAME PDF template as staff
    template_path = 'users/user_account_info_pdf.html'
    context = {
        'user': customer,  # Same variable name as staff view
        'account': account,
        'transactions': transactions,
        'filter_value': filter_value,
        'start_date': start_date,
        'end_date': end_date,
    }
    
    html = get_template(template_path).render(context)
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Account_Statement_{customer.username}.pdf"'
    
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error')
    
    return response


def customer_logout(request):
    """Logout customer by clearing session"""
    request.session.pop('customer_id', None)
    request.session.pop('customer_username', None)
    request.session.pop('is_customer', None)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')
