from django.db import migrations, models


def seed_pricing_rules(apps, schema_editor):
    PricingRule = apps.get_model("users", "PricingRule")

    rows = [
        ("Visiting Card", "Class Card", "", "", 500, "S/S", "550"),
        ("Visiting Card", "Class Card", "", "", 500, "D/S", "850"),
        ("Visiting Card", "Class Card", "", "", 1000, "S/S", "750"),
        ("Visiting Card", "Class Card", "", "", 1000, "D/S", "950"),
        ("Visiting Card", "Synthadic Card", "", "", 500, "S/S", "650"),
        ("Visiting Card", "Synthadic Card", "", "", 500, "D/S", "950"),
        ("Visiting Card", "Synthadic Card", "", "", 1000, "S/S", "850"),
        ("Visiting Card", "Synthadic Card", "", "", 1000, "D/S", "1250"),
        ("Visiting Card", "Matt Card", "", "", 500, "S/S", "750"),
        ("Visiting Card", "Matt Card", "", "", 500, "D/S", "1000"),
        ("Visiting Card", "Matt Card", "", "", 1000, "S/S", "950"),
        ("Visiting Card", "Matt Card", "", "", 1000, "D/S", "1350"),
        ("Bill Book", "A5 Size 1+1", "", "", 10, "", "1500"),
        ("Bill Book", "A5 Size 1+1", "", "", 20, "", "2100"),
        ("Bill Book", "A4 Size 1+1", "", "", 10, "", "2100"),
        ("Bill Book", "A4 Size 1+1", "", "", 20, "", "3500"),
        ("Letter Pad", "A4 Bond Letter", "", "", 500, "", "1700"),
        ("Letter Pad", "A4 Bond Letter", "", "", 1000, "", "2250"),
        ("Brochure (Notice)", "", "A5", "70", 500, "S/S", "600"),
        ("Brochure (Notice)", "", "A5", "70", 500, "D/S", "750"),
        ("Brochure (Notice)", "", "A4", "70", 500, "S/S", "850"),
        ("Brochure (Notice)", "", "A4", "70", 500, "D/S", "1100"),
        ("Brochure (Notice)", "", "A4", "70", 1000, "S/S", "1100"),
        ("Brochure (Notice)", "", "A4", "70", 1000, "D/S", "1450"),
        ("Brochure (Notice)", "", "A3", "70", 500, "S/S", "1450"),
        ("Brochure (Notice)", "", "A3", "70", 500, "D/S", "2100"),
        ("Brochure (Notice)", "", "A3", "70", 1000, "S/S", "1950"),
        ("Brochure (Notice)", "", "A3", "70", 1000, "D/S", "2650"),
        ("Multicolor Brochure", "", "A4", "100", 1000, "S/S", "2100"),
        ("Multicolor Brochure", "", "A4", "100", 1000, "D/S", "2850"),
        ("Multicolor Brochure", "", "A3", "100", 1000, "S/S", "3450"),
        ("Multicolor Brochure", "", "A3", "100", 1000, "D/S", "4650"),
        ("Multicolor Brochure", "", "A4", "130", 1000, "S/S", "3000"),
        ("Multicolor Brochure", "", "A4", "130", 1000, "D/S", "3250"),
        ("Multicolor Brochure", "", "A3", "130", 1000, "S/S", "5850"),
        ("Multicolor Brochure", "", "A3", "130", 1000, "D/S", "6550"),
        ("Multicolor Brochure", "", "A3", "170", 1000, "S/S", "7850"),
        ("Multicolor Brochure", "", "A3", "170", 1000, "D/S", "8550"),
        ("Cover", "6.5 x 4.5 Size", "", "", 1000, "S/S", "1150"),
        ("Cover", "6.5 x 4.5 Size", "", "", 1000, "D/S", "1650"),
        ("Cover", "10.5 x 4.5 Size", "", "", 1000, "S/S", "1450"),
        ("Cover", "10.5 x 4.5 Size", "", "", 1000, "D/S", "1850"),
    ]

    PricingRule.objects.bulk_create(
        PricingRule(
            service=service,
            variant=variant,
            paper_size=paper_size,
            gsm=gsm,
            quantity=quantity,
            print_side=print_side,
            price=price,
        )
        for service, variant, paper_size, gsm, quantity, print_side, price in rows
    )


def remove_seeded_rules(apps, schema_editor):
    PricingRule = apps.get_model("users", "PricingRule")
    PricingRule.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0008_companysettings_multicolor_charges"),
    ]

    operations = [
        migrations.CreateModel(
            name="PricingRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service", models.CharField(max_length=100)),
                ("variant", models.CharField(blank=True, max_length=150)),
                ("paper_size", models.CharField(blank=True, max_length=50)),
                ("gsm", models.CharField(blank=True, max_length=20)),
                ("quantity", models.PositiveIntegerField(default=0)),
                ("print_side", models.CharField(blank=True, max_length=10)),
                ("price", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["service", "variant", "paper_size", "gsm", "quantity", "print_side"],
            },
        ),
        migrations.RunPython(seed_pricing_rules, remove_seeded_rules),
    ]
