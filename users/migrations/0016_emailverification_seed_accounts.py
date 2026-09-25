from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings as django_settings
from django.contrib.auth.hashers import make_password


def seed_auth_accounts(apps, schema_editor):
    User = apps.get_model("auth", "User")
    CompanySettings = apps.get_model("users", "CompanySettings")
    company_settings = CompanySettings.objects.filter(id=1).first()
    default_email = company_settings.email if company_settings else ""

    for username, password in (("admin", "pass@1234"), ("staff", "staff@1234")):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": default_email, "is_active": True},
        )
        user.password = make_password(password)
        user.is_active = True
        if not user.email and default_email:
            user.email = default_email
        user.save()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0015_companysettings_primary_color"),
        migrations.swappable_dependency(django_settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("new_email", models.EmailField(max_length=254)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="email_verifications", to=django_settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.RunPython(seed_auth_accounts, migrations.RunPython.noop),
    ]