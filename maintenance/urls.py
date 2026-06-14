from django.urls import path
from django.contrib.auth.views import (
    PasswordResetView, PasswordResetDoneView,
    PasswordResetConfirmView, PasswordResetCompleteView,
)
from .views import (
    HomeView, DashboardView,
    StudentHomeView, StaffHomeView,
    StudentDashboardView, StaffDashboardView, AdminDashboardView,
    SubmitRequestView, RequestDetailView,
    StatusUpdateView, StaffFeedbackView, RequestAssignView, PriorityOverrideView,
    UserManagementView, ToggleUserActiveView,
    TrendAnalysisView, ReportsView, ReportPDFView, NotificationsView,
    RequestStatusJsonView,
    ProfileView, CustomPasswordChangeView,
    CustomLoginView, register_view, custom_logout_view,
)

urlpatterns = [
    path('',                                    HomeView.as_view(),              name='home'),
    path('dashboard/',                          DashboardView.as_view(),         name='dashboard'),
    path('dashboard/student/',                  StudentHomeView.as_view(),       name='student_home'),
    path('dashboard/student/requests/',         StudentDashboardView.as_view(),  name='student_dashboard'),
    path('dashboard/staff/',                    StaffHomeView.as_view(),         name='staff_home'),
    path('dashboard/staff/queue/',              StaffDashboardView.as_view(),    name='staff_dashboard'),
    path('dashboard/admin/',                    AdminDashboardView.as_view(),    name='admin_dashboard'),
    path('request/new/',                        SubmitRequestView.as_view(),     name='submit_request'),
    path('request/<int:pk>/',                   RequestDetailView.as_view(),     name='request_detail'),
    path('request/<int:pk>/status/',            StatusUpdateView.as_view(),      name='status_update'),
    path('request/<int:pk>/feedback/',          StaffFeedbackView.as_view(),     name='staff_feedback'),
    path('request/<int:pk>/status.json',        RequestStatusJsonView.as_view(), name='request_status_json'),
    path('request/<int:pk>/assign/',            RequestAssignView.as_view(),     name='request_assign'),
    path('request/<int:pk>/override/',          PriorityOverrideView.as_view(),  name='priority_override'),
    path('users/',                              UserManagementView.as_view(),    name='user_management'),
    path('users/<int:pk>/toggle/',              ToggleUserActiveView.as_view(),  name='toggle_user_active'),
    path('analytics/',                          TrendAnalysisView.as_view(),     name='trend_analysis'),
    path('reports/',                            ReportsView.as_view(),           name='reports'),
    path('reports/pdf/',                        ReportPDFView.as_view(),         name='reports_pdf'),
    path('notifications/',                      NotificationsView.as_view(),     name='notifications'),
    path('profile/',                            ProfileView.as_view(),           name='profile'),
    path('password/change/',                    CustomPasswordChangeView.as_view(), name='password_change'),
    path('password/reset/',                     PasswordResetView.as_view(
                                                    template_name='maintenance/password_reset_form.html',
                                                    email_template_name='maintenance/password_reset_email.html',
                                                    subject_template_name='maintenance/password_reset_subject.txt',
                                                    success_url='/password/reset/done/',
                                                ), name='password_reset'),
    path('password/reset/done/',                PasswordResetDoneView.as_view(
                                                    template_name='maintenance/password_reset_done.html',
                                                ), name='password_reset_done'),
    path('password/reset/<uidb64>/<token>/',    PasswordResetConfirmView.as_view(
                                                    template_name='maintenance/password_reset_confirm.html',
                                                    success_url='/password/reset/complete/',
                                                ), name='password_reset_confirm'),
    path('password/reset/complete/',            PasswordResetCompleteView.as_view(
                                                    template_name='maintenance/password_reset_complete.html',
                                                ), name='password_reset_complete'),
    path('login/',                              CustomLoginView.as_view(),       name='login'),
    path('register/',                           register_view,                   name='register'),
    path('logout/',                             custom_logout_view,              name='logout'),
]
