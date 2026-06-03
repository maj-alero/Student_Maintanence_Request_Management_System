from django import forms
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm
from .models import User, MaintenanceRequest


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})

class StudentRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'Student'
        if commit:
            user.save()
        return user

class StaffRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = 'Staff'
        if commit:
            user.save()
        return user

class MaintenanceRequestForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = [
            'hostel_name', 'wing', 'room_number',
            'category', 'location', 'description', 'photo',
            'urgency_level', 'affected_users',
            'time_sensitivity', 'impact_level', 'recurrence',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['hostel_name'].required = True
        self.fields['wing'].required = True
        self.fields['room_number'].required = False
        self.fields['photo'].required = False

class StatusUpdateForm(forms.ModelForm):
    class Meta:
        model = MaintenanceRequest
        fields = ['status']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'})
        }

class AssignmentForm(forms.ModelForm):
    class Meta:
        from .models import Assignment
        model = Assignment
        fields = ['assigned_to', 'notes']
        widgets = {
            'assigned_to': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assigned_to'].queryset = User.objects.filter(role='Staff', is_active=True)

class PriorityOverrideForm(forms.ModelForm):
    class Meta:
        from .models import PriorityClassification
        model = PriorityClassification
        fields = ['priority_label']
        widgets = {
            'priority_label': forms.Select(attrs={'class': 'form-select'})
        }
