import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View, CreateView, DetailView
from django.contrib import messages
from django.contrib.auth.views import LoginView as AuthLoginView, PasswordChangeView
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from .forms import (
    StudentRegistrationForm, StaffRegistrationForm,
    MaintenanceRequestForm, StatusUpdateForm,
    AssignmentForm, PriorityOverrideForm,
    ProfileUpdateForm, CustomPasswordChangeForm,
    StaffFeedbackForm,
)
from .models import User, MaintenanceRequest, PriorityClassification, StatusHistory, Notification, StaffFeedback
from .decorators import student_required, staff_required, staff_or_admin_required
from ml_model.classifier import predict_priority

logger = logging.getLogger(__name__)

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
            return redirect('student_home')
        elif request.user.role == 'Staff':
            return redirect('staff_home')
        elif request.user.role == 'Admin' or request.user.is_superuser:
            return redirect('admin_dashboard')
        return redirect('home')


@method_decorator([login_required, student_required], name='dispatch')
class StudentHomeView(TemplateView):
    template_name = 'maintenance/student_home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = MaintenanceRequest.objects.filter(submitted_by=self.request.user)
        context['total']       = qs.count()
        context['pending']     = qs.filter(status='Pending').count()
        context['in_progress'] = qs.filter(status='In Progress').count()
        context['resolved']    = qs.filter(status='Resolved').count()
        context['recent']      = qs.order_by('-timestamp')[:4]
        return context


@method_decorator([login_required, staff_required], name='dispatch')
class StaffHomeView(TemplateView):
    template_name = 'maintenance/staff_home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        qs = (MaintenanceRequest.objects
              .filter(assignments__assigned_to=self.request.user)
              .distinct())
        context['total']       = qs.count()
        context['pending']     = qs.filter(status='Pending').count()
        context['in_progress'] = qs.filter(status='In Progress').count()
        context['resolved']    = qs.filter(status='Resolved').count()
        context['urgent']      = (qs.filter(status__in=['Pending', 'In Progress'])
                                    .filter(priority__priority_label='High')
                                    .order_by('-timestamp')[:5])
        context['recent']      = qs.order_by('-timestamp')[:4]
        return context

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
        context['feedback_list'] = self.object.feedback.all()
        context['feedback_form'] = StaffFeedbackForm()

        if self.request.user.role == 'Admin' or self.request.user.is_superuser:
            context['assignment_form'] = AssignmentForm()
            context['override_form'] = (
                PriorityOverrideForm(instance=self.object.priority)
                if hasattr(self.object, 'priority')
                else PriorityOverrideForm()
            )

        return context

@method_decorator([login_required, staff_or_admin_required], name='dispatch')
class StaffFeedbackView(View):
    def post(self, request, pk, *args, **kwargs):
        maintenance_request = get_object_or_404(MaintenanceRequest, pk=pk)
        form = StaffFeedbackForm(request.POST)
        if form.is_valid():
            feedback = form.save(commit=False)
            feedback.request = maintenance_request
            feedback.author = request.user
            feedback.save()
            _notify(
                maintenance_request.submitted_by,
                f"Staff update on your request #{maintenance_request.id} "
                f"({maintenance_request.category}): {feedback.message[:120]}"
            )
        return redirect('request_detail', pk=pk)


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
    success_url = '/dashboard/student/'  # redirects to student_home
    
    def form_valid(self, form):
        maintenance_request = form.save(commit=False)
        maintenance_request.submitted_by = self.request.user
        maintenance_request.save()

        StatusHistory.objects.create(
            request=maintenance_request,
            new_status='Pending',
            changed_by=self.request.user
        )

        # AI classification — calls the trained model
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
        except Exception as e:
            logger.exception("predict_priority failed: %s", e)
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

        # Notify all admins of the new request
        for admin in User.objects.filter(role='Admin'):
            _notify(
                admin,
                f"New {priority} priority request #{maintenance_request.id} — "
                f"{maintenance_request.category} at {maintenance_request.hostel_name} "
                f"(submitted by {self.request.user.username}).",
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
class ReportsView(TemplateView):
    template_name = 'maintenance/reports.html'

    # Detailed advice per category
    CATEGORY_ADVICE = {
        'Plumbing': {
            'icon': 'ti-droplet',
            'action': 'Plumbing inspection',
            'steps': [
                'Inspect all supply pipes for leaks, corrosion, or blockages.',
                'Test water pressure at every tap, shower, and toilet outlet.',
                'Check cisterns, traps, and drainage for blockages or slow flow.',
                'Replace worn washers, seals, or aged pipe sections.',
                'Clear blocked drains and check waste-water outlets.',
                'Run water through all outlets for 2–3 minutes and check for discolouration.',
            ],
        },
        'Electrical': {
            'icon': 'ti-bolt',
            'action': 'Electrical safety audit',
            'steps': [
                'Test every socket and switch in the affected area for correct operation.',
                'Inspect the distribution board — check for tripped breakers or burn marks.',
                'Look for exposed, frayed, or improperly routed wiring.',
                'Verify that all fittings and appliances are properly earthed.',
                'Test emergency lighting and any common-area fittings.',
                'Ensure the work is signed off by a certified electrician.',
            ],
        },
        'Carpentry': {
            'icon': 'ti-hammer',
            'action': 'Carpentry maintenance round',
            'steps': [
                'Check all doors for alignment, damaged hinges, and functioning locks.',
                'Inspect window frames, latches, and glass panes for cracks or gaps.',
                'Examine bed frames, wardrobes, shelves, and desks for structural integrity.',
                'Repair or replace broken furniture components.',
                'Sand down rough or splintered surfaces and re-varnish where needed.',
                'Seal any gaps in frames that affect ventilation or security.',
            ],
        },
    }

    DEFAULT_ADVICE = {
        'icon': 'ti-tool',
        'action': 'General maintenance inspection',
        'steps': [
            'Conduct a thorough visual inspection of the reported area.',
            'Photograph all defects before beginning any repair work.',
            'Prioritise issues that affect student safety or basic amenities.',
            'Carry out repairs and document the work completed.',
            'Schedule a follow-up inspection two weeks after completion.',
        ],
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import datetime
        from django.db.models import Count

        period = self.request.GET.get('period', 'monthly')
        delta = datetime.timedelta(days=7 if period == 'weekly' else 30)
        now = timezone.now()
        start = now - delta
        prev_start = start - delta

        qs      = MaintenanceRequest.objects.filter(timestamp__gte=start)
        prev_qs = MaintenanceRequest.objects.filter(timestamp__gte=prev_start, timestamp__lt=start)

        total       = qs.count()
        resolved    = qs.filter(status='Resolved').count()
        unresolved  = total - resolved
        prev_total  = prev_qs.count()
        trend_delta = total - prev_total

        # Hostel + wing + category hotspots for the period
        hotspots = list(
            qs.exclude(hostel_name='')
            .values('hostel_name', 'wing', 'category')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

        # Category-level breakdown
        category_breakdown = list(
            qs.values('category').annotate(count=Count('id')).order_by('-count')
        )

        # Hostel-level totals for the period
        hostel_totals = list(
            qs.exclude(hostel_name='')
            .values('hostel_name').annotate(count=Count('id')).order_by('-count')
        )

        # Recurring reports this period
        recurring_count = qs.filter(recurrence='Yes').count()

        # Unresolved high-priority
        high_unresolved = qs.filter(
            status__in=['Pending', 'In Progress'],
            priority__priority_label='High'
        ).count()

        # Build recommendations
        recommendations = self._build_recommendations(hotspots)

        # Category-level advice (deduplicated by category)
        seen = set()
        category_advice = []
        for row in category_breakdown:
            cat = row['category']
            if cat not in seen:
                seen.add(cat)
                advice = self.CATEGORY_ADVICE.get(cat, self.DEFAULT_ADVICE)
                category_advice.append({
                    'category': cat,
                    'count': row['count'],
                    'icon': advice['icon'],
                    'action': advice['action'],
                    'steps': advice['steps'],
                })

        context.update({
            'period': period,
            'period_label': 'Weekly' if period == 'weekly' else 'Monthly',
            'start_date': start,
            'generated_at': now,
            'total': total,
            'resolved': resolved,
            'unresolved': unresolved,
            'prev_total': prev_total,
            'trend_delta': trend_delta,
            'recurring_count': recurring_count,
            'high_unresolved': high_unresolved,
            'hostel_totals': hostel_totals,
            'recommendations': recommendations,
            'category_advice': category_advice,
        })
        return context

    def _build_recommendations(self, hotspots):
        recs = []
        for spot in hotspots:
            count = spot['count']
            if count >= 5:
                urgency, urgency_cls = 'Critical', 'badge-high'
                note = 'Requires immediate scheduled maintenance this week.'
            elif count >= 3:
                urgency, urgency_cls = 'High', 'badge-medium'
                note = 'Should be addressed within the next 1–2 weeks.'
            else:
                urgency, urgency_cls = 'Monitor', 'badge-accent'
                note = 'Flag for the next routine maintenance cycle.'

            advice = self.CATEGORY_ADVICE.get(spot['category'], self.DEFAULT_ADVICE)
            recs.append({
                'hostel':      spot['hostel_name'],
                'wing':        spot['wing'],
                'category':    spot['category'],
                'count':       count,
                'urgency':     urgency,
                'urgency_cls': urgency_cls,
                'note':        note,
                'action':      advice['action'],
                'steps':       advice['steps'],
                'icon':        advice['icon'],
            })
        return recs


@method_decorator([login_required, admin_required], name='dispatch')
class ReportPDFView(View):
    def get(self, request):
        from django.db.models import Count
        import datetime
        from io import BytesIO
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.lib.colors import HexColor, white
            from reportlab.lib.units import mm
            from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                             Table, TableStyle, HRFlowable, PageBreak)
            from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        except ImportError:
            return HttpResponse('ReportLab is not installed. Run: pip install reportlab', status=500)

        period = request.GET.get('period', 'monthly')
        delta = datetime.timedelta(days=7 if period == 'weekly' else 30)
        now = timezone.now()
        start = now - delta
        prev_start = start - delta
        period_label = 'Weekly' if period == 'weekly' else 'Monthly'

        qs = MaintenanceRequest.objects.filter(timestamp__gte=start)
        total = qs.count()
        resolved = qs.filter(status='Resolved').count()
        unresolved = total - resolved
        trend_delta = total - MaintenanceRequest.objects.filter(
            timestamp__gte=prev_start, timestamp__lt=start).count()
        recurring_count = qs.filter(recurrence='Yes').count()
        high_unresolved = qs.filter(
            status__in=['Pending', 'In Progress'],
            priority__priority_label='High'
        ).count()
        hotspots = list(
            qs.exclude(hostel_name='')
            .values('hostel_name', 'wing', 'category')
            .annotate(count=Count('id')).order_by('-count')
        )
        hostel_totals = list(
            qs.exclude(hostel_name='')
            .values('hostel_name').annotate(count=Count('id')).order_by('-count')
        )
        recommendations = ReportsView()._build_recommendations(hotspots)

        # colours
        ACCENT     = HexColor('#4F46E5')
        SUCCESS_C  = HexColor('#059669')
        CRITICAL_C = HexColor('#DC2626')
        HIGH_C     = HexColor('#D97706')
        LIGHT_BG   = HexColor('#F5F4F1')
        LIGHT_ACC  = HexColor('#EEF2FF')
        BORDER_C   = HexColor('#E5E7EB')
        ERR_BG     = HexColor('#FEF2F2')
        WARN_BG    = HexColor('#FFFBEB')
        TEXT_P     = HexColor('#1A1A2E')
        TEXT_S     = HexColor('#5C5C7A')
        TEXT_M     = HexColor('#9898B0')
        PAGE_W, _  = A4
        MARGIN     = 20 * mm
        COL_W      = PAGE_W - 2 * MARGIN

        # paragraph factory — flat, no nesting
        def ps(fontName='Helvetica', fontSize=10, textColor=None, alignment=0,
               leading=14, leftIndent=0, spaceBefore=0, spaceAfter=2, backColor=None):
            kw = dict(fontName=fontName, fontSize=fontSize,
                      textColor=textColor or TEXT_P, alignment=alignment,
                      leading=leading, leftIndent=leftIndent,
                      spaceBefore=spaceBefore, spaceAfter=spaceAfter)
            if backColor:
                kw['backColor'] = backColor
            return ParagraphStyle('_', **kw)

        def P(text, **kw):
            return Paragraph(text, ps(**kw))

        def sec(text):
            return P(text, fontName='Helvetica-Bold', fontSize=8,
                     textColor=TEXT_M, spaceBefore=18, spaceAfter=8)

        # document
        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                rightMargin=MARGIN, leftMargin=MARGIN,
                                topMargin=26 * mm, bottomMargin=22 * mm)
        story = []

        # brand banner
        banner = Table(
            [[P('<b>FixIt — Student Maintenance Request Management System</b>',
                fontSize=11, textColor=ACCENT)]],
            colWidths=[COL_W])
        banner.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_ACC),
            ('BOX', (0, 0), (-1, -1), 1, ACCENT),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 14),
            ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ]))
        story += [banner, Spacer(1, 14)]
        story.append(P(f'{period_label} Preventive Maintenance Report',
                       fontName='Helvetica-Bold', fontSize=22, spaceAfter=4))
        story.append(P(
            f'<font color="#5C5C7A">Period: {start.strftime("%d %b %Y")} - '
            f'{now.strftime("%d %b %Y")}&#160;|&#160;'
            f'Generated: {now.strftime("%d %b %Y, %H:%M")}</font>',
            fontSize=10))
        story.append(HRFlowable(width='100%', thickness=0.8, color=BORDER_C,
                                spaceBefore=12, spaceAfter=16))

        # summary stats table (flat — no nested tables)
        story.append(sec('EXECUTIVE SUMMARY'))
        trend_hex = '#DC2626' if trend_delta > 0 else ('#059669' if trend_delta < 0 else '#5C5C7A')
        trend_str = ('+' if trend_delta > 0 else '') + str(trend_delta)
        cw6 = COL_W / 6
        stat_tbl = Table(
            [
                ['Total Reports', 'Resolved', 'Unresolved', 'Recurring',
                 'High-Priority Open', 'vs Prev. Period'],
                [
                    P(f'<b>{total}</b>', fontSize=20, alignment=TA_CENTER),
                    P(f'<b>{resolved}</b>', fontSize=20, alignment=TA_CENTER, textColor=SUCCESS_C),
                    P(f'<b>{unresolved}</b>', fontSize=20, alignment=TA_CENTER, textColor=CRITICAL_C),
                    P(f'<b>{recurring_count}</b>', fontSize=20, alignment=TA_CENTER, textColor=HIGH_C),
                    P(f'<b>{high_unresolved}</b>', fontSize=20, alignment=TA_CENTER, textColor=CRITICAL_C),
                    P(f'<b><font color="{trend_hex}">{trend_str}</font></b>',
                      fontSize=20, alignment=TA_CENTER),
                ],
            ],
            colWidths=[cw6] * 6,
        )
        stat_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7.5),
            ('TEXTCOLOR', (0, 0), (-1, 0), TEXT_M),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, BORDER_C),
        ]))
        story.append(stat_tbl)

        if not recommendations:
            story += [Spacer(1, 16),
                      P('No maintenance requests were submitted during this period.',
                        textColor=TEXT_S)]
        else:
            # ── priority maintenance zones ────────────────────────────────
            # Each card = 2-col header table (one level, no nesting) +
            #             flat Paragraphs for action + steps + note.
            story.append(Spacer(1, 4))
            story.append(sec('PRIORITY MAINTENANCE ZONES'))
            story.append(P(
                '<b>Critical</b> = 5+ reports&#160;|&#160;'
                '<b>High</b> = 3-4 reports&#160;|&#160;'
                '<b>Monitor</b> = 1-2 reports',
                fontSize=8.5, textColor=TEXT_S, spaceAfter=10))

            urg_colors = {
                'Critical': ('#DC2626', ERR_BG),
                'High':     ('#D97706', WARN_BG),
                'Monitor':  ('#4F46E5', LIGHT_ACC),
            }

            for rec in recommendations:
                urg_hex, hdr_bg = urg_colors.get(rec['urgency'], ('#4F46E5', LIGHT_ACC))
                rpt = f'{rec["count"]} report{"s" if rec["count"] != 1 else ""}'

                # single-level 2-col header table (safe)
                hdr = Table(
                    [[
                        P(f'<b>{rec["hostel"]} - Wing {rec["wing"]}</b><br/>'
                          f'<font size="9" color="#5C5C7A">'
                          f'{rec["category"]} | {rpt} this period</font>',
                          fontSize=11, leading=16),
                        P(f'<b><font color="{urg_hex}">{rec["urgency"]}</font></b>',
                          fontSize=11, alignment=TA_RIGHT),
                    ]],
                    colWidths=[COL_W * 0.65, COL_W * 0.35],
                )
                hdr.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), hdr_bg),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                    ('LEFTPADDING', (0, 0), (0, -1), 12),
                    ('RIGHTPADDING', (-1, 0), (-1, -1), 12),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LINEBELOW', (0, 0), (-1, -1), 0.5, BORDER_C),
                ]))
                story.append(hdr)

                # flat paragraphs — no table nesting
                story.append(P(f'<b>Recommended action:</b> {rec["action"]}',
                               fontSize=9, leftIndent=12, spaceBefore=7, spaceAfter=4))
                for i, step in enumerate(rec['steps'], 1):
                    story.append(P(f'{i}.  {step}',
                                   fontSize=9, textColor=TEXT_S, leading=13,
                                   leftIndent=24, spaceBefore=2, spaceAfter=2))
                story.append(P(rec['note'],
                               fontSize=8, textColor=TEXT_M,
                               leftIndent=12, spaceBefore=6, spaceAfter=0))
                story.append(HRFlowable(width='100%', thickness=0.4, color=BORDER_C,
                                        spaceBefore=10, spaceAfter=10))

            # ── hostel volume (flat table, one level) ─────────────────────
            if hostel_totals:
                story.append(PageBreak())
                story.append(sec('ISSUE VOLUME BY HOSTEL'))
                max_c = hostel_totals[0]['count']
                BAR_W = COL_W * 0.50
                for row in hostel_totals:
                    filled = max(BAR_W * row['count'] / max_c, 2)
                    empty  = BAR_W - filled
                    cnt    = f'{row["count"]} report{"s" if row["count"] != 1 else ""}'
                    # two-col flat bar: filled cell + empty cell
                    if empty > 1:
                        bar = Table([['', '']], colWidths=[filled, empty])
                        bar.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (0, 0), ACCENT),
                            ('BACKGROUND', (1, 0), (1, 0), LIGHT_BG),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('LEFTPADDING', (0, 0), (-1, -1), 0),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ]))
                    else:
                        bar = Table([['']], colWidths=[BAR_W])
                        bar.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, -1), ACCENT),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('LEFTPADDING', (0, 0), (-1, -1), 0),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ]))
                    row_tbl = Table(
                        [[P(f'<b>{row["hostel_name"]}</b>', fontSize=9),
                          bar,
                          P(cnt, fontSize=9, textColor=TEXT_S, alignment=TA_RIGHT)]],
                        colWidths=[COL_W * 0.30, BAR_W, COL_W * 0.20],
                    )
                    row_tbl.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('TOPPADDING', (0, 0), (-1, -1), 3),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ('LINEBELOW', (0, 0), (-1, -1), 0.3, BORDER_C),
                        ('LEFTPADDING', (0, 0), (0, 0), 0),
                        ('RIGHTPADDING', (-1, 0), (-1, 0), 0),
                    ]))
                    story.append(row_tbl)

            # ── quick reference table ─────────────────────────────────────
            story.append(Spacer(1, 20))
            story.append(sec('QUICK REFERENCE SUMMARY'))
            uhex_map = {'Critical': '#DC2626', 'High': '#D97706', 'Monitor': '#4F46E5'}
            ref_rows = [['Hostel', 'Wing', 'Issue Type', 'Reports', 'Urgency', 'Action Required']]
            for rec in recommendations:
                uhex = uhex_map.get(rec['urgency'], '#4F46E5')
                ref_rows.append([
                    P(f'<b>{rec["hostel"]}</b>', fontSize=8.5),
                    P(f'Wing {rec["wing"]}', fontSize=8.5, textColor=TEXT_S),
                    P(rec['category'], fontSize=8.5, textColor=TEXT_S),
                    P(str(rec['count']), fontSize=8.5, alignment=TA_CENTER),
                    P(f'<b><font color="{uhex}">{rec["urgency"]}</font></b>',
                      fontSize=8.5, alignment=TA_CENTER),
                    P(rec['action'], fontSize=8, textColor=TEXT_S),
                ])
            ref_tbl = Table(
                ref_rows,
                colWidths=[COL_W * 0.23, COL_W * 0.09, COL_W * 0.12,
                           COL_W * 0.08, COL_W * 0.11, COL_W * 0.37],
                repeatRows=1,
            )
            ref_tbl.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 7.5),
                ('TEXTCOLOR', (0, 0), (-1, 0), TEXT_M),
                ('ALIGN', (3, 0), (4, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ('LEFTPADDING', (0, 0), (-1, -1), 7),
                ('RIGHTPADDING', (0, 0), (-1, -1), 7),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER_C),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LIGHT_BG]),
            ]))
            story.append(ref_tbl)

        def on_page(canvas, doc):
            canvas.saveState()
            canvas.setFont('Helvetica', 7.5)
            canvas.setFillColor(TEXT_M)
            canvas.drawString(MARGIN, 14 * mm,
                f'FixIt SMRMS  |  {period_label} Maintenance Report  |  '
                f'{now.strftime("%d %b %Y")}')
            canvas.drawRightString(PAGE_W - MARGIN, 14 * mm,
                f'Page {canvas.getPageNumber()}')
            canvas.restoreState()

        doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        buf.seek(0)
        filename = f'maintenance_report_{period}_{now.strftime("%Y%m%d")}.pdf'
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


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


@method_decorator(login_required, name='dispatch')
class ProfileView(View):
    template_name = 'maintenance/profile.html'

    def get(self, request):
        form = ProfileUpdateForm(instance=request.user)
        context = self._build_context(request, form)
        return render(request, self.template_name, context)

    def post(self, request):
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('profile')
        context = self._build_context(request, form)
        return render(request, self.template_name, context)

    def _build_context(self, request, form):
        from django.db.models import Count, Avg, F, ExpressionWrapper, DurationField
        user = request.user
        context = {'form': form}

        if user.role == 'Student':
            qs = MaintenanceRequest.objects.filter(submitted_by=user)
            context['stats'] = {
                'total':       qs.count(),
                'pending':     qs.filter(status='Pending').count(),
                'in_progress': qs.filter(status='In Progress').count(),
                'resolved':    qs.filter(status='Resolved').count(),
            }
            context['category_breakdown'] = list(
                qs.values('category').annotate(count=Count('id')).order_by('-count')
            )
            context['recent_requests'] = qs.order_by('-timestamp')[:5]

        elif user.role == 'Staff':
            qs = MaintenanceRequest.objects.filter(
                assignments__assigned_to=user
            ).distinct()
            resolved_qs = qs.filter(status='Resolved', resolved_at__isnull=False)
            avg_res = resolved_qs.aggregate(
                avg=Avg(ExpressionWrapper(
                    F('resolved_at') - F('timestamp'),
                    output_field=DurationField()
                ))
            )['avg']
            if avg_res:
                total_h = avg_res.total_seconds() / 3600
                avg_res_display = f"{total_h/24:.1f}d" if total_h >= 24 else f"{total_h:.1f}h"
            else:
                avg_res_display = '—'

            context['stats'] = {
                'total':           qs.count(),
                'pending':         qs.filter(status='Pending').count(),
                'in_progress':     qs.filter(status='In Progress').count(),
                'resolved':        resolved_qs.count(),
                'avg_resolution':  avg_res_display,
            }
            context['category_breakdown'] = list(
                qs.values('category').annotate(count=Count('id')).order_by('-count')
            )
            context['recent_requests'] = qs.order_by('-timestamp')[:5]

        return context


class CustomPasswordChangeView(PasswordChangeView):
    form_class = CustomPasswordChangeForm
    template_name = 'maintenance/password_change.html'
    success_url = '/profile/'

    def form_valid(self, form):
        messages.success(self.request, 'Password changed successfully.')
        return super().form_valid(form)