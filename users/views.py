from datetime import datetime, timedelta
from django.db import IntegrityError, transaction
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse
from django.template.loader import get_template
from django.utils import timezone
from decimal import Decimal
from xhtml2pdf import pisa

from .models import UsersNew, Account, Transaction, Employee
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

def custom_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        role = request.POST.get('role')

        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            # Check if user has the selected role
            if role:
                # If user is SUPERUSER, they can log in as ANY role (Admin/Manager/Supervisor/Clerk)
                # If user is NORMAL, they must have the specific group assigned
                if not user.is_superuser:
                    if not user.groups.filter(name=role).exists():
                        messages.error(request, f"Access Denied: You are not assigned the role '{role}'.")
                        return render(request, 'users/login.html')
            
            if user.is_active:
                login(request, user)
                
                # Redirect based on role
                # Superuser -> Employee List by default (Manager View) or User List if they chose Supervisor/Clerk
                if user.is_superuser:
                    if role == 'Supervisor' or role == 'Clerk':
                        return redirect('user_list')
                    return redirect('employee_list') # Default for Admin/Manager selection

                if is_manager(user):
                    return redirect('employee_list')
                elif is_supervisor(user) or is_clerk(user):
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
                employee = form.save()
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

    results = []
    for user in users:
        # Get status safely
        account_status = 'N/A'
        kyc_status = 'N/A'
        account_no = 'N/A'
        
        if hasattr(user, 'account'):
            account_status = user.account.get_account_status_display()
            kyc_status = user.account.get_kyc_status_display()
            account_no = user.account.account_no

        results.append({
            'id': user.pk,
            'username': user.username,
            'email': user.email,
            'contact': user.contact,
            'joining_date': user.joining_date.strftime('%Y-%m-%d'),
            'account_no': account_no,
            'account_status': account_status,
            'kyc_status': kyc_status,
        })

    return JsonResponse({'results': results})


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
    """Process deposit or withdrawal - Supervisor & Clerk"""
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

    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['txn_type'] == 'withdraw':
                if form.cleaned_data['amount'] > account.current_balance:
                    messages.error(request, 'Insufficient balance')
                    return redirect('make_transaction', user_id=user.pk)
                new_balance = account.current_balance - form.cleaned_data['amount']
            else:  # deposit
                new_balance = account.current_balance + form.cleaned_data['amount']

            account.current_balance = new_balance
            account.save()
            
            txn = Transaction(
                account=account,
                current_balance=new_balance,
                txn_type=form.cleaned_data['txn_type'],
                amount=form.cleaned_data['amount'],
                description=form.cleaned_data.get('description', '')
            )
            txn.save()
            
            messages.success(request, 'Transaction successful!')
            return redirect('user_account_info', user_id=user.pk)
    else:
        form = TransactionForm()

    return render(request, 'users/transaction_form.html', {
        'form': form,
        'user': user,
        'current_balance': current_balance
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
