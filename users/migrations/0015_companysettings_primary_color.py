from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0014_seed_invitation_multicolor_prices"),
    ]

    operations = [
        migrations.AddField(
            model_name="companysettings",
            name="primary_color",
            field=models.CharField(default="#6D4AFF", max_length=7),
        ),
    ]
