from .models import CompanySettings


def theme_settings(request):
    settings_record = CompanySettings.objects.only("primary_color").first()
    return {
        "primary_color": (
            settings_record.primary_color
            if settings_record and settings_record.primary_color
            else "#6D4AFF"
        ),
    }
