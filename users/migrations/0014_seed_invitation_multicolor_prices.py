from django.db import migrations


def seed_invitation_prices(apps, schema_editor):
    CompanySettings = apps.get_model("users", "CompanySettings")
    settings_record, _ = CompanySettings.objects.get_or_create(id=1)
    charges = dict(settings_record.multicolor_charges or {})

    rows = [
        ("A5 210x140", 500, "single", {"gloss": "4100"}),
        ("A4", 500, "single", {"gloss": "3900"}),
        ("A4", 500, "double", {"gloss": "6100", "matt3d": "6400"}),
        ("19x7 / 14x9.5", 500, "single", {"gloss": "9500", "matt3d": "9900", "dripoff": "12100", "uva": "19100"}),
        ("A3 420x280 / 210x570", 500, "single", {"gloss": "10900", "matt3d": "11500", "dripoff": "12700", "uva": "19700"}),
        ("A3 Royal", 500, "single", {"gloss": "11900", "matt3d": "12500", "dripoff": "13500", "uva": "20100"}),
        ("29x9 / 14.5x19.5", 500, "single", {"gloss": "14500", "matt3d": "15300", "dripoff": "16700", "uva": "21900"}),
        ("24.5x11.5", 500, "single", {"gloss": "18700", "matt3d": "19500", "dripoff": "20900", "uva": "26300"}),
        ("35x11 / 22x17", 500, "single", {"gloss": "22100", "matt3d": "23100", "dripoff": "40300", "uva": "42100"}),
        ("A5 210x140", 1000, "single", {"gloss": "5900", "matt3d": "6100"}),
        ("A4", 1000, "single", {"gloss": "6500"}),
        ("A4", 1000, "double", {"gloss": "8500", "matt3d": "9300", "uva": "19700"}),
        ("19x7 / 14x9.5", 1000, "single", {"gloss": "12900", "matt3d": "13500", "dripoff": "16700", "uva": "21900"}),
        ("A3 420x280 / 210x570", 1000, "single", {"gloss": "16500", "matt3d": "17500", "dripoff": "20300", "uva": "23700"}),
        ("A3 Royal", 1000, "single", {"gloss": "18500", "matt3d": "19700", "dripoff": "21700", "uva": "24300"}),
        ("29x9 / 14.5x19.5", 1000, "single", {"gloss": "23500", "matt3d": "24900", "dripoff": "27700", "uva": "29100"}),
        ("24.5x11.5", 1000, "single", {"gloss": "27500", "matt3d": "29100", "dripoff": "31900", "uva": "33300"}),
        ("35x11 / 22x17", 1000, "single", {"gloss": "34300", "matt3d": "36300", "dripoff": "40300", "uva": "42100"}),
    ]

    if not any(str(key).startswith("MC|") for key in charges):
        for paper_size, copies, side, finishes in rows:
            for finish, price in finishes.items():
                charges[f"MC|{paper_size}|300|{copies}|{side}|{finish}"] = price

    settings_record.multicolor_charges = charges
    settings_record.save(update_fields=["multicolor_charges", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0013_bill_invoice_type"),
    ]

    operations = [
        migrations.RunPython(seed_invitation_prices, migrations.RunPython.noop),
    ]