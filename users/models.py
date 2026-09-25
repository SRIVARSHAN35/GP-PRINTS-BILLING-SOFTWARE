from django.conf import settings
from django.db import models


def default_printing_charges():
    return {
        "A4_single_single": "400",
        "A4_single_double": "800",
        "A4_double_single": "800",
        "A4_double_double": "800",
        "A3_single_single": "800",
        "A3_single_double": "1600",
        "A3_double_single": "1600",
        "A3_double_double": "1700",
        "visiting": "0",
        "custom": "0"
    }


def default_design_charges():
    return {
        "A4_single": "300",
        "A4_double": "600",
        "A3_single": "500",
        "A3_double": "1000",
        "visiting": "200"
    }


def default_multicolor_charges():
    charges = {
        "A4_300_500": "5600",
        "A4_300_1000": "7800",
        "A4_350_500": "6200",
        "A4_350_1000": "8400",
        "A3_300_500": "7800",
        "A3_300_1000": "10500",
        "A3_350_500": "9000",
        "A3_350_1000": "12000",
    }

    for paper_size in ("A4", "A3", "210x280mm"):
        for gsm in ("200", "250", "300", "350", "400"):
            for copies in ("500", "1000"):
                charges.setdefault(
                    f"{paper_size}_{gsm}_{copies}",
                    "0",
                )

    return charges


def multicolor_finish_definitions():
    return (
        ("gloss", "Gloss"),
        ("matt3d", "Matt 3D"),
        ("dripoff", "Drip-off"),
        ("uva", "UVA"),
    )


def multicolor_rate_definitions(charges=None):
    charges = charges or default_multicolor_charges()
    fields = []
    seen_keys = set()

    for paper_size in ("A4", "A3", "210x280mm"):
        for gsm in ("200", "250", "300", "350", "400"):
            for copies in ("500", "1000"):
                for side in ("single", "double"):
                    key = f"{paper_size}_{gsm}_{copies}_{side}"
                    value = charges.get(key)
                    if value is None:
                        value = charges.get(f"{paper_size}_{gsm}_{copies}", "0")
                    fields.append({
                        "key": key,
                        "paper_size": paper_size,
                        "gsm": gsm,
                        "copies": copies,
                        "side": side,
                        "finish": "standard",
                        "value": str(value),
                    })
                    seen_keys.add(key)

    for key, value in sorted(charges.items()):
        if key in seen_keys:
            continue

        if key.startswith("MC|"):
            parts = key.split("|")
            if len(parts) != 6:
                continue
            _, paper_size, gsm, copies, side, finish = parts
            fields.append({
                "key": key,
                "paper_size": paper_size,
                "gsm": gsm,
                "copies": copies,
                "side": side,
                "finish": finish,
                "value": str(value),
            })
            continue

        parts = key.split("_")
        if len(parts) not in {3, 4}:
            continue

        paper_size, gsm, copies = parts[:3]
        side = parts[3] if len(parts) == 4 else "single"
        fields.append({
            "key": key,
            "paper_size": paper_size,
            "gsm": gsm,
            "copies": copies,
            "side": side,
            "finish": "standard",
            "value": str(value),
        })

    return fields


class CompanySettings(models.Model):

    company_name = models.CharField(
        max_length=150,
        default="GP PRINTS"
    )

    primary_color = models.CharField(
        max_length=7,
        default="#6D4AFF"
    )

    phone = models.CharField(
        max_length=30,
        blank=True
    )

    email = models.EmailField(
        blank=True
    )

    address = models.TextField(
        blank=True
    )

    logo = models.ImageField(
        upload_to="company/",
        blank=True,
        null=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    invoice_prefix = models.CharField(
        max_length=20,
        default="GP-"
    )

    default_gst = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    invoice_footer = models.TextField(
        default="Thank you for choosing GP Prints!"
    )

    printing_charges = models.JSONField(
        default=default_printing_charges
    )

    design_charges = models.JSONField(
        default=default_design_charges
    )

    multicolor_charges = models.JSONField(
        default=default_multicolor_charges
    )

    lamination_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    embossing_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    def __str__(self):
        return self.company_name


class EmailVerification(models.Model):

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_verifications",
    )

    new_email = models.EmailField()
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class Customer(models.Model):

    name = models.CharField(max_length=100)

    phone = models.CharField(max_length=15)

    email = models.EmailField(blank=True)

    address = models.TextField(blank=True)

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.name


class Product(models.Model):

    model_number = models.CharField(
        max_length=50,
        unique=True
    )

    name = models.CharField(
        max_length=100
    )

    category = models.CharField(
        max_length=100
    )

    paper_type = models.CharField(
        max_length=100
    )

    paper_size = models.CharField(
        max_length=50
    )

    print_type = models.CharField(
        max_length=100
    )

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    stock = models.PositiveIntegerField(
        default=0
    )

    STATUS_CHOICES = [
        ('available', 'Available'),
        ('out_of_stock', 'Out of Stock'),
        ('discontinued', 'Discontinued'),
    ]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='available'
    )

    description = models.TextField(
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.model_number} - {self.name}"


class PricingRule(models.Model):

    service = models.CharField(max_length=100)

    variant = models.CharField(max_length=150, blank=True)

    paper_size = models.CharField(max_length=50, blank=True)

    gsm = models.CharField(max_length=20, blank=True)

    quantity = models.PositiveIntegerField(default=0)

    print_side = models.CharField(max_length=10, blank=True)

    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    unit = models.CharField(max_length=50, blank=True)

    description = models.TextField(blank=True, default="")

    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service", "variant", "paper_size", "gsm", "quantity", "print_side"]

    def __str__(self):
        details = " / ".join(
            value for value in (
                self.variant,
                self.paper_size,
                f"{self.gsm} GSM" if self.gsm else "",
                str(self.quantity) if self.quantity else "",
                self.print_side,
            )
            if value
        )
        return f"{self.service}: {details}" if details else self.service


class Bill(models.Model):

    INVOICE_TYPE_CARDS = "cards"
    INVOICE_TYPE_CONFIGURED_SERVICE = "configured_service"
    INVOICE_TYPE_MULTICOLOR = "multicolor"

    INVOICE_TYPE_CHOICES = (
        (INVOICE_TYPE_CARDS, "Cards"),
        (INVOICE_TYPE_CONFIGURED_SERVICE, "Configured service"),
        (INVOICE_TYPE_MULTICOLOR, "Multicolor"),
    )

    invoice_number = models.CharField(
        max_length=50,
        unique=True
    )

    invoice_type = models.CharField(
        max_length=30,
        choices=INVOICE_TYPE_CHOICES,
        default=INVOICE_TYPE_CARDS,
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    customer_name = models.CharField(
        max_length=100
    )

    customer_phone = models.CharField(
        max_length=15
    )

    customer_email = models.EmailField(
        blank=True
    )

    customer_address = models.TextField(
        blank=True
    )

    products = models.JSONField(
        default=list
    )

    multicolor_items = models.JSONField(
        default=list,
        blank=True
    )

    total_copies = models.PositiveIntegerField(
        default=0
    )

    paper_size = models.CharField(
        max_length=50,
        blank=True
    )

    printing_color = models.CharField(
        max_length=50,
        blank=True
    )

    printing_page = models.CharField(
        max_length=50,
        blank=True
    )

    printing_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    design_required = models.CharField(
        max_length=10,
        default="no"
    )

    design_page = models.CharField(
        max_length=50,
        blank=True
    )

    design_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    lamination = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    embossing = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    other_charges = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    card_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    subtotal = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    gst = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0
    )

    gst_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    final_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    def __str__(self):
        return self.invoice_number