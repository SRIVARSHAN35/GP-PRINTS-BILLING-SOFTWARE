from django.db import migrations


def seed_other_services(apps, schema_editor):
    PricingRule = apps.get_model("users", "PricingRule")
    PricingRule.objects.bulk_create(
        PricingRule(service=service, variant="Available", price="0")
        for service in ("Flex", "Calendar", "Rubber Stamp", "Poster")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0009_pricingrule"),
    ]

    operations = [
        migrations.RunPython(seed_other_services, migrations.RunPython.noop),
    ]