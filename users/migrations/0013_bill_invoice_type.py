from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0012_pricingrule_dynamic_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="invoice_type",
            field=models.CharField(
                choices=[
                    ("cards", "Cards"),
                    ("configured_service", "Configured service"),
                    ("multicolor", "Multicolor"),
                ],
                default="cards",
                max_length=30,
            ),
        ),
    ]