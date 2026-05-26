from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View, CreateView, DetailView
from django.contrib import messages
from django.contrib.auth.views import LoginView as AuthLoginView
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.http import JsonResponse
from django.db.models import Q
from .forms import (
    StudentRegistrationForm, StaffRegistrationForm,
    MaintenanceRequestForm, StatusUpdateForm,
    AssignmentForm, PriorityOverrideForm,
)
from .models import User, MaintenanceRequest, PriorityClassification, StatusHistory, Notification
from .decorators import student_required, staff_required, staff_or_admin_required
from ml_model.classifier import predict_priority


def _notify(recipient, message):
    """Create an in-app notification."""
    Notification.objects.create(recipient=recipient, message=message)

class HomeView(View):
    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, 'pages/index.html')

class DashboardView(View):
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role == 'Student':
            return redirect('student_dashboard')
        elif request.user.role == 'Staff':
            return redirect('staff_dashboard')
        elif request.user.role == 'Admin' or request.user.is_superuser:
            return redirect('admin_dashboard')
        return redirect('home')

@method_decorator([login_required, student_required], name='dispatch')
class StudentDashboardView(TemplateView):
    template_name = 'maintenance/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['requests'] = MaintenanceRequest.objects.filter(submitted_by=self.request.user).order_by('-timestamp')
        return context

@method_decorator([login_required, staff_required], name='dispatch')
class StaffDashboardView(TemplateView):
    template_name = 'maintenance/staff_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['requests'] = (
            MaintenanceRequest.objects
            .filter(assignments__assigned_to=self.request.user)
            .order_by('-timestamp')
            .distinct()
        )
        return context

@method_decorator(login_required, name='dispatch')
class RequestDetailView(DetailView):
    model = MaintenanceRequest
    template_name = 'maintenance/request_detail.html'
    context_object_name = 'req'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_form'] = StatusUpdateForm(instance=self.object)
        context['history'] = self.object.status_history.all().order_by('-changed_at')
        
        if self.request.user.role == 'Admin' or self.request.user.is_superuser:
            context['assignment_form'] = AssignmentForm()
            context['override_form'] = (
                PriorityOverrideForm(instance=self.object.priority)
                if hasattr(self.object, 'priority')
                else PriorityOverrideForm()
            )
        
        return context

@method_decorator([login_required, staff_or_admin_required], name='dispatch')
class StatusUpdateView(View):
    def post(self, request, pk, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=pk)
        old_status = maintenance_request.status
        form = StatusUpdateForm(request.POST, instance=maintenance_request)
        if form.is_valid():
            new_req = form.save(commit=False)
            if new_req.status == 'Resolved' and not maintenance_request.resolved_at:
                new_req.resolved_at = timezone.now()
            new_req.save()
            if old_status != new_req.status:
                StatusHistory.objects.create(
                    request=new_req,
                    previous_status=old_status,
                    new_status=new_req.status,
                    changed_by=request.user
                )
                # In-app notification to the student
                _notify(
                    new_req.submitted_by,
                    f"Your request #{new_req.id} ({new_req.category} - {new_req.location}) "
                    f"has been updated to '{new_req.status}'.",
                )
                # Email the student if they have an address
                if new_req.submitted_by.email:
                    try:
                        send_mail(
                            subject=f"[FixIt] Request #{new_req.id} updated to '{new_req.status}'",
                            message=(
                                f"Hi {new_req.submitted_by.username},\n\n"
                                f"Your maintenance request #{new_req.id} "
                                f"({new_req.category} at {new_req.location}) "
                                f"has been updated to: {new_req.status}.\n\n"
                                f"Log in to FixIt to see the full details.\n\n"
                                f"- The FixIt Team"
                            ),
                            from_email=django_settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[new_req.submitted_by.email],
                            fail_silently=True,
                        )
                    except Exception:
                        pass
            messages.success(request, 'Status updated successfully.')
        return redirect('request_detail', pk=pk)

@method_decorator([login_required, student_required], name='dispatch')
class SubmitRequestView(CreateView):
    template_name = 'maintenance/submit_request.html'
    form_class = MaintenanceRequestForm
    success_url = '/dashboard/student/'
    
    def form_valid(self, form):
        maintenance_request = form.save(commit=False)
        maintenance_request.submitted_by = self.request.user
        maintenance_request.save()

        StatusHistory.objects.create(
            request=maintenance_request,
            new_status='Pending',
            changed_by=self.request.user
        )

        # AI classification — call the trained Random Forest model
        try:
            priority = predict_priority(
                category         = form.cleaned_data['category'],
                location         = form.cleaned_data['location'],
                urgency_level    = form.cleaned_data['urgency_level'],
                affected_users   = form.cleaned_data['affected_users'],
                time_sensitivity = int(form.cleaned_data['time_sensitivity']),
                impact_level     = form.cleaned_data['impact_level'],
                recurrence       = form.cleaned_data['recurrence'],
            )
        except Exception:
            # Fallback to Medium if the model fails for any reason
            priority = 'Medium'

        PriorityClassification.objects.create(
            request=maintenance_request,
            priority_label=priority
        )

        # Notify the student their request was received
        _notify(
            self.request.user,
            f"Your request #{maintenance_request.id} ({maintenance_request.category} - "
            f"{maintenance_request.location}) was submitted. AI priority: {priority}.",
        )

        messages.success(self.request, f'Request submitted successfully. Priority assigned: {priority}.')
        return super().form_valid(form)

class CustomLoginView(AuthLoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True
    
    def get_success_url(self):
        return '/dashboard/'

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        role_type = request.POST.get('role_type', 'Student')
        if role_type == 'Staff':
            form = StaffRegistrationForm(request.POST)
        else:
            form = StudentRegistrationForm(request.POST)
            
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful.')
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
            return render(request, 'accounts/register.html', {'form': form, 'role_type': role_type})
    else:
        form = StudentRegistrationForm()
        return render(request, 'accounts/register.html', {'form': form, 'role_type': 'Student'})
    
def custom_logout_view(request):
    logout(request)
    return redirect('home')

def admin_required(function):
    def wrap(request, *args, **kwargs):
        if request.user.is_authenticated and (request.user.role == 'Admin' or request.user.is_superuser):
            return function(request, *args, **kwargs)
        messages.error(request, "You are not authorized to view this page.")
        return redirect('dashboard')
    wrap.__doc__ = function.__doc__
    wrap.__name__ = function.__name__
    return wrap

@method_decorator([login_required, admin_required], name='dispatch')
class AdminDashboardView(TemplateView):
    template_name = 'maintenance/admin_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        queryset = MaintenanceRequest.objects.all().order_by('-timestamp')

        search = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status')
        category = self.request.GET.get('category')
        priority = self.request.GET.get('priority')
        date = self.request.GET.get('date')

        if search:
            queryset = queryset.filter(
                Q(description__icontains=search) |
                Q(category__icontains=search) |
                Q(submitted_by__username__icontains=search) |
                Q(hostel_name__icontains=search) |
                Q(room_number__icontains=search)
            )
        if status:
            queryset = queryset.filter(status=status)
        if category:
            queryset = queryset.filter(category=category)
        if priority:
            queryset = queryset.filter(priority__priority_label=priority)
        if date:
            queryset = queryset.filter(timestamp__date=date)
            
        context['requests'] = queryset
        
        context['categories'] = sorted(list(set(MaintenanceRequest.objects.values_list('category', flat=True))))
        context['priorities'] = sorted(list(set(PriorityClassification.objects.values_list('priority_label', flat=True))))
        return context

@method_decorator([login_required, admin_required], name='dispatch')
class RequestAssignView(View):
    def post(self, request, pk, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=pk)
        form = AssignmentForm(request.POST)
        if form.is_valid():
            assignment = form.save(commit=False)
            assignment.request = maintenance_request
            assignment.assigned_by = request.user
            assignment.save()
            
            old_status = maintenance_request.status
            maintenance_request.status = 'In Progress'
            maintenance_request.save()
            
            if old_status != 'In Progress':
                StatusHistory.objects.create(
                    request=maintenance_request,
                    previous_status=old_status,
                    new_status='In Progress',
                    changed_by=request.user
                )
            # Notify the assigned staff member
            _notify(
                assignment.assigned_to,
                f"You have been assigned request #{maintenance_request.id} "
                f"({maintenance_request.category} - {maintenance_request.location}).",
            )
            # Notify the student their request is moving forward
            _notify(
                maintenance_request.submitted_by,
                f"Your request #{maintenance_request.id} has been assigned to a staff member and is now In Progress.",
            )
            messages.success(request, f'Request assigned to {assignment.assigned_to.username}.')
        else:
            messages.error(request, 'Error assigning request.')
        return redirect('request_detail', pk=pk)

@method_decorator([login_required, admin_required], name='dispatch')
class PriorityOverrideView(View):
    def post(self, request, pk, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=pk)
        from .forms import PriorityOverrideForm
        
        if hasattr(maintenance_request, 'priority'):
            priority_obj = maintenance_request.priority
        else:
            priority_obj = PriorityClassification(request=maintenance_request)
            
        form = PriorityOverrideForm(request.POST, instance=priority_obj)
        if form.is_valid():
            saved = form.save()
            # Notify the student their priority was changed
            _notify(
                maintenance_request.submitted_by,
                f"The priority of your request #{maintenance_request.id} has been "
                f"changed to '{saved.priority_label}' by an administrator.",
            )
            # Log as a status history entry (status itself doesn't change)
            StatusHistory.objects.create(
                request=maintenance_request,
                previous_status=maintenance_request.status,
                new_status=maintenance_request.status,
                changed_by=request.user
            )
            messages.success(request, 'Priority overridden successfully.')
        else:
            messages.error(request, 'Error overriding priority.')
        return redirect('request_detail', pk=pk)

@method_decorator([login_required, admin_required], name='dispatch')
class UserManagementView(TemplateView):
    template_name = 'maintenance/user_management.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['users_list'] = User.objects.all().order_by('-date_joined')
        return context

@method_decorator([login_required, admin_required], name='dispatch')
class ToggleUserActiveView(View):
    def post(self, request, pk, *args, **kwargs):
        user_to_toggle = get_object_or_404(User, pk=pk)
        if user_to_toggle == request.user:
            messages.error(request, "You cannot deactivate your own account.")
        else:
            user_to_toggle.is_active = not user_to_toggle.is_active
            user_to_toggle.save()
            status = "activated" if user_to_toggle.is_active else "deactivated"
            messages.success(request, f"User {user_to_toggle.username} has been {status}.")
        return redirect('user_management')
        
@method_decorator([login_required, admin_required], name='dispatch')
class TrendAnalysisView(TemplateView):
    template_name = 'maintenance/trend_analysis.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Count, Avg, F, Case, When, IntegerField, ExpressionWrapper, DurationField
        from django.db.models.functions import TruncDate
        import datetime

        thirty_days_ago = timezone.now() - datetime.timedelta(days=30)

        # ── existing charts ──────────────────────────────────────────────────
        category_counts = list(MaintenanceRequest.objects.values('category').annotate(count=Count('id')).order_by('-count'))
        location_counts = list(MaintenanceRequest.objects.values('location').annotate(count=Count('id')).order_by('-count'))
        volume_over_time = list(
            MaintenanceRequest.objects
            .annotate(date=TruncDate('timestamp'))
            .values('date').annotate(count=Count('id')).order_by('date')
        )
        for item in volume_over_time:
            item['date'] = item['date'].isoformat()
        priority_dist = list(PriorityClassification.objects.values('priority_label').annotate(count=Count('id')).order_by('priority_label'))

        # ── hostel & wing breakdown ──────────────────────────────────────────
        hostel_counts = list(
            MaintenanceRequest.objects
            .exclude(hostel_name='')
            .values('hostel_name').annotate(count=Count('id')).order_by('-count')
        )
        wing_counts = list(
            MaintenanceRequest.objects
            .exclude(wing='')
            .values('wing').annotate(count=Count('id')).order_by('wing')
        )

        # ── avg resolution time by category ─────────────────────────────────
        avg_res_qs = list(
            MaintenanceRequest.objects
            .filter(status='Resolved', resolved_at__isnull=False)
            .values('category')
            .annotate(avg_dur=Avg(ExpressionWrapper(F('resolved_at') - F('timestamp'), output_field=DurationField())))
            .order_by('category')
        )
        for item in avg_res_qs:
            if item['avg_dur']:
                total_h = item['avg_dur'].total_seconds() / 3600
                item['display'] = f"{total_h/24:.1f}d" if total_h >= 24 else f"{total_h:.1f}h"
                item['hours'] = round(total_h, 1)
            else:
                item['display'] = '—'
                item['hours'] = 0

        # ── recurrence rate by category ──────────────────────────────────────
        recurrence_by_cat = list(
            MaintenanceRequest.objects
            .values('category')
            .annotate(
                total=Count('id'),
                recurring_count=Count(Case(When(recurrence='Yes', then=1), output_field=IntegerField()))
            )
            .order_by('-recurring_count')
        )
        for item in recurrence_by_cat:
            item['rate'] = round(item['recurring_count'] / item['total'] * 100) if item['total'] else 0

        # ── hostel × category hotspots ────────────────────────────────────────
        hostel_category_hotspots = list(
            MaintenanceRequest.objects
            .exclude(hostel_name='')
            .values('hostel_name', 'category')
            .annotate(count=Count('id'))
            .order_by('-count')[:12]
        )

        # ── hostel × wing hotspots ────────────────────────────────────────────
        hostel_wing_hotspots = list(
            MaintenanceRequest.objects
            .exclude(hostel_name='')
            .values('hostel_name', 'wing')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )

        # ── high-priority unresolved backlog ──────────────────────────────────
        high_priority_backlog = (
            MaintenanceRequest.objects
            .filter(status__in=['Pending', 'In Progress'])
            .filter(priority__priority_label='High')
            .order_by('-timestamp')[:8]
        )

        # ── predictive insights (hostel/wing/category aware, last 30 days) ───
        recent_hotspots = list(
            MaintenanceRequest.objects
            .filter(timestamp__gte=thirty_days_ago)
            .exclude(hostel_name='')
            .values('hostel_name', 'wing', 'category')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        context['insights'] = [x for x in recent_hotspots if x['count'] > 1]

        # ── top recurring issues (unchanged) ─────────────────────────────────
        context['recurring_issues'] = MaintenanceRequest.objects.filter(recurrence='Yes').order_by('-timestamp')[:8]

        context['avg_resolution'] = avg_res_qs
        context['recurrence_by_cat'] = recurrence_by_cat
        context['hostel_category_hotspots'] = hostel_category_hotspots
        context['hostel_wing_hotspots'] = hostel_wing_hotspots
        context['high_priority_backlog'] = high_priority_backlog

        context['chart_data'] = {
            'categories': {'labels': [x['category'] for x in category_counts], 'data': [x['count'] for x in category_counts]},
            'locations':  {'labels': [x['location']  for x in location_counts],  'data': [x['count'] for x in location_counts]},
            'volume':     {'labels': [x['date']       for x in volume_over_time],  'data': [x['count'] for x in volume_over_time]},
            'priority':   {'labels': [x['priority_label'] for x in priority_dist], 'data': [x['count'] for x in priority_dist]},
            'hostels':    {'labels': [x['hostel_name'] for x in hostel_counts],    'data': [x['count'] for x in hostel_counts]},
            'wings':      {'labels': [f"Wing {x['wing']}" for x in wing_counts],   'data': [x['count'] for x in wing_counts]},
            'avg_res':    {'labels': [x['category'] for x in avg_res_qs],          'data': [x['hours'] for x in avg_res_qs]},
            'recurrence': {'labels': [x['category'] for x in recurrence_by_cat],   'data': [x['rate']  for x in recurrence_by_cat]},
        }
        return context


@method_decorator(login_required, name='dispatch')
class NotificationsView(TemplateView):
    template_name = 'maintenance/notifications.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        notifs = Notification.objects.filter(recipient=self.request.user)
        notifs.filter(is_read=False).update(is_read=True)  # mark all as read on open
        context['notifications'] = notifs
        return context


@method_decorator(login_required, name='dispatch')
class RequestStatusJsonView(View):
    def get(self, request, pk, *args, **kwargs):
        req = get_object_or_404(MaintenanceRequest, pk=pk)
        if (request.user != req.submitted_by
                and request.user.role not in ('Staff', 'Admin')
                and not request.user.is_superuser):
            return JsonResponse({'error': 'forbidden'}, status=403)
        latest = req.status_history.order_by('-changed_at').first()
        return JsonResponse({
            'status': req.status,
            'resolution_time': req.resolution_time,
            'latest_changed_at': latest.changed_at.isoformat() if latest else None,
            'latest_changed_by': latest.changed_by.username if latest and latest.changed_by else None,
        })