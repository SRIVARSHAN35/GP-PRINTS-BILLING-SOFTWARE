import json
import secrets
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from django.shortcuts import get_object_or_404, render, redirect
from django.http import FileResponse, Http404, JsonResponse
from django.db.models import Q, Sum
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.core.mail import send_mail
import os
from .models import (
    Bill,
    CompanySettings,
    Customer,
    Product,
    PricingRule,
    EmailVerification,
    default_design_charges,
    default_multicolor_charges,
    default_printing_charges,
    multicolor_rate_definitions,
)


# =========================
# LOGIN
# =========================

def loginpage(request):

    if request.method == "POST":

        username = request.POST.get("username")
        password = request.POST.get("password")

        auth_user = authenticate(request, username=username, password=password)

        # Preserve the existing legacy admin password while auth users are being adopted.
        if not auth_user and username == "admin" and password == "1234":
            auth_user = User.objects.filter(username="admin", is_active=True).first()

        if auth_user:

            request.session["logged_in"] = True
            request.session["username"] = auth_user.username
            request.session["role"] = "admin" if auth_user.username == "admin" else "staff"

            return redirect("dashboard")


        # WRONG LOGIN
        else:

            return render(
                request,
                "login.html",
                {
                    "error": "Invalid username or password"
                }
            )

    return render(request, "login.html")


def get_multicolor_price_for_bill(
    paper_size, gsm, copies, company_settings, side=None, finish=None
):
    if not company_settings:
        return Decimal("0")

    multicolor_charges = company_settings.multicolor_charges or {}
    if not multicolor_charges:
        return Decimal("0")

    gsm_value = str(gsm or "300")
    copies_count = int(copies or 0)
    copies_bucket = 500 if copies_count <= 500 else 1000
    side_value = str(side or "").strip().lower()
    side_key = "double" if side_value in {"double", "d/s", "ds", "2", "2-side"} else "single" if side_value in {"single", "s/s", "ss", "1", "1-side"} else ""
    finish_key = str(finish or "").strip().lower().replace(" ", "")

    key_candidates = [
        f"{paper_size}_{gsm_value}_{copies_bucket}",
        f"{paper_size}_{gsm_value}_500",
        f"{paper_size}_{gsm_value}_1000",
    ]
    if side_key:
        key_candidates = [
            f"MC|{paper_size}|{gsm_value}|{copies_bucket}|{side_key}|{finish_key}",
            f"{paper_size}_{gsm_value}_{copies_bucket}_{side_key}",
            f"{paper_size}_{gsm_value}_{copies_bucket}",
            f"{paper_size}_{gsm_value}_{side_key}",
            *key_candidates,
        ]

    normalized_keys = {
        str(existing_key).lower(): value
        for existing_key, value in multicolor_charges.items()
    }

    for key in key_candidates:
        value = normalized_keys.get(key.lower())
        if value is None:
            continue
        try:
            return Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            continue

    return Decimal("0")


def _sum_multicolor_amounts(queryset):
    total = Decimal("0")

    for bill in queryset:
        for item in bill.multicolor_items or []:
            try:
                amount_value = item.get("amount") or item.get("price") or "0"
                total += Decimal(str(amount_value))
            except (TypeError, ValueError, InvalidOperation):
                continue

    return total


# =========================
# DASHBOARD
# =========================

def dashboard(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    customer_count = Customer.objects.count()
    product_count = Product.objects.count()

    today = timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    todays_bills = Bill.objects.filter(
        created_at__date=today
    )
    this_week_bills = Bill.objects.filter(
        created_at__date__gte=week_start
    )
    this_month_bills = Bill.objects.filter(
        created_at__date__gte=month_start
    )
    all_bills = Bill.objects.all()

    today_order_count = todays_bills.count()
    today_total_sales = (
        todays_bills.aggregate(
            total=Sum("final_amount")
        )["total"]
        or 0
    )
    today_total_copies = (
        todays_bills.aggregate(
            total=Sum("total_copies")
        )["total"]
        or 0
    )
    today_gst_collected = (
        todays_bills.aggregate(
            total=Sum("gst_amount")
        )["total"]
        or 0
    )
    this_week_total_sales = (
        this_week_bills.aggregate(
            total=Sum("final_amount")
        )["total"]
        or 0
    )
    this_month_total_sales = (
        this_month_bills.aggregate(
            total=Sum("final_amount")
        )["total"]
        or 0
    )
    total_revenue = (
        all_bills.aggregate(
            total=Sum("final_amount")
        )["total"]
        or 0
    )
    multicolor_total_sales = _sum_multicolor_amounts(all_bills)

    invoice_search = request.GET.get("invoice_search", "").strip()
    recent_invoices = Bill.objects.all()

    if invoice_search:
        recent_invoices = recent_invoices.filter(
            Q(invoice_number__icontains=invoice_search) |
            Q(customer_name__icontains=invoice_search) |
            Q(customer_phone__icontains=invoice_search)
        )

    recent_invoices = recent_invoices.order_by("-created_at")[:10]

    return render(
        request,
        "dashboard.html",
        {
            "customer_count": customer_count,
            "product_count": product_count,
            "today_order_count": today_order_count,
            "today_total_sales": today_total_sales,
            "today_total_copies": today_total_copies,
            "today_gst_collected": today_gst_collected,
            "this_week_total_sales": this_week_total_sales,
            "this_month_total_sales": this_month_total_sales,
            "total_revenue": total_revenue,
            "multicolor_total_sales": multicolor_total_sales,
            "recent_invoices": recent_invoices,
            "invoice_search": invoice_search,
            "username": request.session.get("username"),
            "role": request.session.get("role")
        }
    )


def _pricing_rule_payload(post_data):
    service = (post_data.get("service") or "").strip()
    variant = (post_data.get("variant") or "").strip()
    paper_size = (post_data.get("paper_size") or "").strip()
    gsm = (post_data.get("gsm") or "").strip()
    quantity_raw = (post_data.get("quantity") or "0").strip()
    print_side = (post_data.get("print_side") or "").strip()
    price_raw = (post_data.get("price") or "0").strip()
    unit = (post_data.get("unit") or "").strip()
    description = (post_data.get("description") or "").strip()
    is_active = post_data.get("active") == "on"

    if not service:
        raise ValueError("Category is required.")

    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a valid whole number.")

    if quantity < 0:
        raise ValueError("Quantity cannot be negative.")

    try:
        price = Decimal(price_raw)
    except (TypeError, InvalidOperation, ValueError):
        raise ValueError("Price must be a valid number.")

    if price < 0:
        raise ValueError("Price cannot be negative.")

    return {
        "service": service,
        "variant": variant,
        "paper_size": paper_size,
        "gsm": gsm,
        "quantity": quantity,
        "print_side": print_side,
        "price": str(price),
        "unit": unit,
        "description": description,
        "active": is_active,
    }


def add_pricing_rule(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.session.get("role") != "admin":
        return redirect("dashboard")

    if request.method != "POST":
        return redirect("settings_page")

    try:
        payload = _pricing_rule_payload(request.POST)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("settings_page")

    PricingRule.objects.create(**payload)
    messages.success(request, f"{payload['service']} pricing rule added successfully.")
    return redirect("settings_page")


def _can_change_account_email(request, target_user):
    if request.session.get("role") == "admin":
        return True
    return request.session.get("username") == target_user.username


def request_email_change(request):
    if not request.session.get("logged_in"):
        return redirect("loginpage")
    if request.method != "POST":
        return redirect("settings_page")

    target_user = get_object_or_404(
        User,
        id=request.POST.get("user_id"),
        is_active=True,
    )
    if not _can_change_account_email(request, target_user):
        messages.error(request, "You can only change your own email address.")
        return redirect("settings_page")

    new_email = request.POST.get("new_email", "").strip().lower()
    if not new_email:
        messages.error(request, "Enter a new email address.")
        return redirect("settings_page")

    code = f"{secrets.randbelow(1000000):06d}"
    EmailVerification.objects.filter(user=target_user, used=False).update(used=True)
    verification = EmailVerification.objects.create(
        user=target_user,
        new_email=new_email,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=10),
    )

    try:
        send_mail(
            "GP Prints email verification code",
            f"Your GP Prints verification code is {code}. It expires in 10 minutes.",
            None,
            [new_email],
            fail_silently=False,
        )
    except Exception:
        verification.delete()
        messages.error(request, "The verification email could not be sent. Check email configuration.")
        return redirect("settings_page")

    request.session["email_verification_id"] = verification.id
    messages.success(request, "Verification code sent to the new email address.")
    return redirect("settings_page")


def verify_email_change(request):
    if not request.session.get("logged_in"):
        return redirect("loginpage")
    if request.method != "POST":
        return redirect("settings_page")

    verification = get_object_or_404(
        EmailVerification,
        id=request.session.get("email_verification_id"),
        used=False,
    )
    if not _can_change_account_email(request, verification.user):
        messages.error(request, "You are not allowed to verify this email change.")
        return redirect("settings_page")
    if verification.expires_at <= timezone.now():
        verification.used = True
        verification.save(update_fields=["used"])
        request.session.pop("email_verification_id", None)
        messages.error(request, "This verification code has expired.")
        return redirect("settings_page")
    if verification.attempts >= 5:
        verification.used = True
        verification.save(update_fields=["used"])
        request.session.pop("email_verification_id", None)
        messages.error(request, "Too many incorrect attempts. Request a new code.")
        return redirect("settings_page")

    code = request.POST.get("verification_code", "").strip()
    if not check_password(code, verification.code_hash):
        verification.attempts += 1
        verification.save(update_fields=["attempts"])
        messages.error(request, "Invalid verification code.")
        return redirect("settings_page")

    verification.user.email = verification.new_email
    verification.user.save(update_fields=["email"])
    verification.used = True
    verification.save(update_fields=["used"])
    request.session.pop("email_verification_id", None)
    messages.success(request, "Email address updated successfully.")
    return redirect("settings_page")


def settings_page(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    is_admin = request.session.get("role") == "admin"
    if request.method == "POST" and not is_admin:
        return redirect("dashboard")

    settings_record, created = CompanySettings.objects.get_or_create(
        id=1
    )

    settings_record.printing_charges = {
        **default_printing_charges(),
        **(settings_record.printing_charges or {}),
    }
    settings_record.design_charges = {
        **default_design_charges(),
        **(settings_record.design_charges or {}),
    }
    settings_record.multicolor_charges = {
        **{key: str(value) for key, value in default_multicolor_charges().items()},
        **{key: str(value) for key, value in (settings_record.multicolor_charges or {}).items()},
    }

    multicolor_rate_fields = multicolor_rate_definitions(
        settings_record.multicolor_charges
    )

    if request.method == "POST":

        if not is_admin:
            return redirect("dashboard")

        settings_record.company_name = request.POST.get(
            "company_name",
            "GP PRINTS"
        ).strip()
        primary_color = request.POST.get("primary_color", "#6D4AFF").strip()
        if (
            len(primary_color) != 7
            or not primary_color.startswith("#")
            or any(character not in "0123456789abcdefABCDEF" for character in primary_color[1:])
        ):
            primary_color = "#6D4AFF"
        settings_record.primary_color = primary_color.upper()
        settings_record.phone = request.POST.get("phone", "").strip()
        settings_record.email = request.POST.get("email", "").strip()
        settings_record.address = request.POST.get("address", "").strip()

        if request.FILES.get("logo"):
            settings_record.logo = request.FILES["logo"]

        settings_record.invoice_prefix = request.POST.get(
            "invoice_prefix",
            "GP-"
        ).strip()
        settings_record.default_gst = request.POST.get(
            "default_gst",
            "0"
        ) or "0"
        settings_record.invoice_footer = request.POST.get(
            "invoice_footer",
            "Thank you for choosing GP Prints!"
        ).strip()
        settings_record.lamination_charge = request.POST.get(
            "lamination_charge",
            "0"
        ) or "0"
        settings_record.embossing_charge = request.POST.get(
            "embossing_charge",
            "0"
        ) or "0"

        printing_charges = default_printing_charges()
        printing_charges.update(settings_record.printing_charges or {})
        settings_record.printing_charges = {
            key: request.POST.get(key, value) or "0"
            for key, value in printing_charges.items()
        }

        design_charges = default_design_charges()
        design_charges.update(settings_record.design_charges or {})
        settings_record.design_charges = {
            key: request.POST.get(key, value) or "0"
            for key, value in design_charges.items()
        }

        multicolor_rates = {}
        for index in range(len(multicolor_rate_fields)):
            prefix = f"multicolor_rate_{index}_"
            original_key = multicolor_rate_fields[index]["key"]
            original_parts = original_key.split("|") if original_key.startswith("MC|") else original_key.split("_")
            paper_size = request.POST.get(
                f"{prefix}paper_size",
                ""
            ).strip().upper()
            gsm = request.POST.get(
                f"{prefix}gsm",
                ""
            ).strip()
            copies_value = request.POST.get(
                f"{prefix}copies",
                ""
            ).strip()
            side = request.POST.get(
                f"{prefix}side",
                ""
            ).strip().lower()
            finish = request.POST.get(
                f"{prefix}finish",
                ""
            ).strip().lower().replace(" ", "")
            price_value = request.POST.get(
                f"{prefix}price",
                ""
            ).strip()

            if original_key.startswith("MC|") and len(original_parts) == 6:
                side = side or original_parts[4]
                finish = finish or original_parts[5]

            if not any((paper_size, gsm, copies_value, side, finish, price_value)):
                continue

            if not all((paper_size, gsm, copies_value, price_value)):
                if original_key.startswith("MC|") and len(original_parts) == 6:
                    paper_size = paper_size or original_parts[1]
                    gsm = gsm or original_parts[2]
                    copies_value = copies_value or original_parts[3]
                    side = side or original_parts[4]
                    finish = finish or original_parts[5]
                elif len(original_parts) not in {3, 4}:
                    continue
                else:
                    paper_size = paper_size or original_parts[0].upper()
                    gsm = gsm or original_parts[1]
                    copies_value = copies_value or original_parts[2]
                    side = side or (original_parts[3] if len(original_parts) == 4 else "single")
                    finish = finish or "standard"
                price_value = price_value or str(
                    settings_record.multicolor_charges.get(
                        original_key,
                        "0"
                    )
                )

            try:
                copies = int(copies_value)
                price = Decimal(price_value)
            except (TypeError, ValueError, InvalidOperation):
                continue

            if copies < 1 or price < 0:
                continue

            if side not in {"single", "double"}:
                side = "single"

            if finish and finish != "standard":
                key = f"MC|{paper_size}|{gsm}|{copies}|{side}|{finish}"
                multicolor_rates[key] = format(price, "f")
                continue

            legacy_key = f"{paper_size}_{gsm}_{copies}"
            key = f"{paper_size}_{gsm}_{copies}_{side}"
            multicolor_rates[key] = format(price, "f")
            multicolor_rates[legacy_key] = format(price, "f")

        for index in range(1, 4):
            prefix = f"new_multicolor_{index}_"
            paper_size = request.POST.get(
                f"{prefix}paper_size",
                ""
            ).strip().upper()
            gsm = request.POST.get(
                f"{prefix}gsm",
                ""
            ).strip()
            copies_value = request.POST.get(
                f"{prefix}copies",
                ""
            ).strip()
            side = request.POST.get(
                f"{prefix}side",
                ""
            ).strip().lower()
            finish = request.POST.get(
                f"{prefix}finish",
                ""
            ).strip().lower().replace(" ", "")
            price_value = request.POST.get(
                f"{prefix}price",
                ""
            ).strip()

            if not all((paper_size, gsm, copies_value, price_value)):
                continue

            try:
                copies = int(copies_value)
                price = Decimal(price_value)
            except (TypeError, ValueError, InvalidOperation):
                continue

            if copies < 1 or price < 0:
                continue

            side = side if side in {"single", "double"} else "single"
            if finish and finish != "standard":
                key = f"MC|{paper_size}|{gsm}|{copies}|{side}|{finish}"
                multicolor_rates[key] = format(price, "f")
                continue

            legacy_key = f"{paper_size}_{gsm}_{copies}"
            key = f"{paper_size}_{gsm}_{copies}_{side}"
            multicolor_rates[key] = format(price, "f")
            multicolor_rates[legacy_key] = format(price, "f")

        settings_record.multicolor_charges = multicolor_rates

        deleted_rule_ids = {
            int(value)
            for value in request.POST.getlist("delete_pricing_rule")
            if value.isdigit()
        }
        for rule in PricingRule.objects.all():
            if rule.id in deleted_rule_ids:
                rule.delete()
                continue

            prefix = f"rule_{rule.id}_"
            rule.service = request.POST.get(f"{prefix}service", rule.service).strip()
            rule.variant = request.POST.get(f"{prefix}variant", "").strip()
            rule.paper_size = request.POST.get(f"{prefix}paper_size", "").strip()
            rule.gsm = request.POST.get(f"{prefix}gsm", "").strip()
            rule.quantity = int(request.POST.get(f"{prefix}quantity", rule.quantity) or 0)
            rule.print_side = request.POST.get(f"{prefix}print_side", "").strip()
            rule.price = request.POST.get(f"{prefix}price", rule.price) or "0"
            rule.unit = request.POST.get(f"{prefix}unit", rule.unit or "").strip()
            rule.description = request.POST.get(f"{prefix}description", rule.description or "").strip()
            rule.active = request.POST.get(f"{prefix}active") == "on"
            rule.save()

        for index in range(1, 4):
            service = request.POST.get(f"new_{index}_service", "").strip()
            if service:
                try:
                    quantity = int(request.POST.get(f"new_{index}_quantity", 0) or 0)
                    price = Decimal(request.POST.get(f"new_{index}_price", "0") or "0")
                except (TypeError, ValueError, InvalidOperation):
                    continue

                if price < 0 or quantity < 0:
                    continue

                PricingRule.objects.create(
                    service=service,
                    variant=request.POST.get(f"new_{index}_variant", "").strip(),
                    paper_size=request.POST.get(f"new_{index}_paper_size", "").strip(),
                    gsm=request.POST.get(f"new_{index}_gsm", "").strip(),
                    quantity=quantity,
                    print_side=request.POST.get(f"new_{index}_print_side", "").strip(),
                    price=price,
                    unit=request.POST.get(f"new_{index}_unit", "").strip(),
                    description=request.POST.get(f"new_{index}_description", "").strip(),
                    active=request.POST.get(f"new_{index}_active") == "on",
                )

        settings_record.save()
        messages.success(request, "Settings updated successfully.")
        return redirect("settings_page")

    pricing_rules = list(PricingRule.objects.all())
    pricing_groups = {}
    for rule in pricing_rules:
        pricing_groups.setdefault(rule.service or "General", []).append(rule)

    return render(
        request,
        "settings.html",
        {
            "settings_record": settings_record,
            "pricing_rules": pricing_rules,
            "pricing_groups": dict(sorted(pricing_groups.items())),
            "multicolor_rate_fields": multicolor_rate_fields,
            "username": request.session.get("username"),
            "role": request.session.get("role"),
            "is_admin": is_admin,
            "account_users": User.objects.filter(is_active=True).order_by("username"),
            "pending_email_verification": EmailVerification.objects.filter(
                id=request.session.get("email_verification_id"),
                used=False,
            ).select_related("user").first(),
        }
    )


def reports(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    bills = Bill.objects.all().order_by("-created_at")

    return render(
        request,
        "reports.html",
        {
            "bills": bills,
            "role": request.session.get("role"),
            "username": request.session.get("username")
        }
    )


def edit_bill(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.session.get("role") != "admin":
        return redirect("reports")

    bill = get_object_or_404(Bill, id=id)

    if request.method == "POST":

        bill.customer_name = request.POST.get("customer_name", "").strip()
        bill.customer_phone = request.POST.get("customer_phone", "").strip()
        bill.customer_email = request.POST.get("customer_email", "").strip()
        bill.customer_address = request.POST.get("customer_address", "").strip()
        bill.printing_charge = request.POST.get("printing_charge", 0)
        bill.design_charge = request.POST.get("design_charge", 0)
        bill.lamination = request.POST.get("lamination", 0)
        bill.embossing = request.POST.get("embossing", 0)
        bill.gst_amount = request.POST.get("gst_amount", 0)
        bill.discount = request.POST.get("discount", 0)
        bill.subtotal = request.POST.get("subtotal", 0)
        bill.final_amount = request.POST.get("final_amount", 0)
        bill.save()

        return redirect("reports")

    return render(
        request,
        "editbill.html",
        {
            "bill": bill,
            "role": request.session.get("role")
        }
    )


def delete_bill(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.session.get("role") != "admin":
        return redirect("reports")

    bill = get_object_or_404(Bill, id=id)
    bill.delete()

    return redirect("reports")


def generate_invoice_pdf(bill, pdf_path):

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    try:
        pdfmetrics.registerFont(
            TTFont("InvoiceArial", "C:\\Windows\\Fonts\\arial.ttf")
        )
        font = "InvoiceArial"
    except Exception:
        font = "Helvetica"

    pdf = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    left = 48
    right = width - 48
    y = height - 58

    def text(value):
        return str(value or "-")

    def money(value):
        return "₹" + format(float(value or 0), ",.2f")

    def heading(value):
        nonlocal y
        pdf.setFont(font, 13)
        pdf.setFillColor(colors.HexColor("#555555"))
        pdf.drawString(left, y, value.upper())
        y -= 22

    def detail(label, value, x, line_y):
        pdf.setFont(font, 10)
        pdf.setFillColor(colors.HexColor("#555555"))
        pdf.drawString(x, line_y, label)
        pdf.setFont(font, 10)
        pdf.setFillColor(colors.HexColor("#222222"))
        pdf.drawString(x + 78, line_y, text(value))

    logo_path = os.path.join(
        settings.BASE_DIR,
        "users",
        "static",
        "images",
        "gp-logo.png"
    )

    if os.path.exists(logo_path):
        pdf.drawImage(logo_path, left, y - 34, width=62, height=40, preserveAspectRatio=True)

    pdf.setFont(font, 27)
    pdf.setFillColor(colors.HexColor("#222222"))
    pdf.drawString(left + 78, y, "GP PRINTS")
    pdf.setFont(font, 11)
    pdf.setFillColor(colors.HexColor("#666666"))
    pdf.drawString(left + 78, y - 19, "Professional Printing Solutions")
    pdf.setFont(font, 28)
    pdf.setFillColor(colors.HexColor("#222222"))
    pdf.drawRightString(right, y, "INVOICE")
    pdf.setFont(font, 11)
    pdf.setFillColor(colors.HexColor("#555555"))
    pdf.drawRightString(right, y - 20, "Invoice No: " + bill.invoice_number)
    pdf.drawRightString(
        right,
        y - 34,
        "Date: " + bill.created_at.strftime("%d-%m-%Y")
    )
    y -= 68
    pdf.setStrokeColor(colors.HexColor("#222222"))
    pdf.line(left, y, right, y)
    y -= 42

    heading("Bill To")
    detail("Name:", bill.customer_name, left, y)
    detail("Phone:", bill.customer_phone, left, y - 16)
    detail("Email:", bill.customer_email, left, y - 32)
    detail("Address:", bill.customer_address, left, y - 48)
    detail("Invoice No:", bill.invoice_number, 330, y)
    detail("Total Copies:", bill.total_copies, 330, y - 16)
    detail("Payment Status:", "Pending", 330, y - 32)
    y -= 82

    heading("Product Details")
    columns = [left, left + 80, left + 235, left + 330, left + 395, right]
    pdf.setFillColor(colors.HexColor("#222222"))
    pdf.rect(left, y - 18, right - left, 22, fill=1, stroke=0)
    pdf.setFont(font, 10)
    pdf.setFillColor(colors.white)
    for label, x in zip(
        ["Model No.", "Product", "Category", "Qty", "Price", "Amount"],
        columns
    ):
        pdf.drawString(x + 5, y - 13, label)
    y -= 39

    for item in bill.products:
        pdf.setFont(font, 10)
        pdf.setFillColor(colors.HexColor("#222222"))
        values = [
            item.get("model_number", ""),
            item.get("name", ""),
            item.get("category", ""),
            item.get("quantity", 0),
            money(item.get("price", 0)),
            money(item.get("amount", 0))
        ]
        for value, x in zip(values, columns):
            pdf.drawString(x + 5, y, text(value)[:24])
        pdf.setStrokeColor(colors.HexColor("#dddddd"))
        pdf.line(left, y - 7, right, y - 7)
        y -= 29

    if bill.multicolor_items:
        y -= 12
        heading("Multicolor Printing Items")
        columns = [left, left + 175, left + 260, left + 345, right]
        pdf.setFillColor(colors.HexColor("#222222"))
        pdf.rect(left, y - 18, right - left, 22, fill=1, stroke=0)
        pdf.setFont(font, 10)
        pdf.setFillColor(colors.white)
        for label, x in zip(["Paper Size", "GSM", "Copies", "Side", "Amount"], columns):
            pdf.drawString(x + 5, y - 13, label)
        y -= 39
        for item in bill.multicolor_items:
            pdf.setFont(font, 10)
            pdf.setFillColor(colors.HexColor("#222222"))
            values = [
                item.get("paper_size", ""),
                str(item.get("gsm", "")) + " GSM",
                item.get("copies", 0),
                item.get("side", "single"),
                money(item.get("amount", item.get("price", 0))),
            ]
            for value, x in zip(values, columns):
                pdf.drawString(x + 5, y, text(value)[:24])
            pdf.setStrokeColor(colors.HexColor("#dddddd"))
            pdf.line(left, y - 8, right, y - 8)
            y -= 29

    if bill.invoice_type in {"cards", ""}:
        y -= 12
        heading("Printing Details")
        pdf.setFillColor(colors.HexColor("#f7f7f7"))
        pdf.rect(left, y - 64, right - left, 72, fill=1, stroke=1)
        detail("Paper Size:", bill.paper_size, left + 12, y - 14)
        detail("Copies:", bill.total_copies, 330, y - 14)
        detail("Printing Color:", bill.printing_color, left + 12, y - 34)
        detail("Printing Pages:", bill.printing_page, 330, y - 34)
        detail("Printing Charge:", money(bill.printing_charge), left + 12, y - 54)
        y -= 100

        heading("Design Details")
        pdf.setFillColor(colors.HexColor("#f7f7f7"))
        pdf.rect(left, y - 64, right - left, 72, fill=1, stroke=1)
        detail("Design Required:", bill.design_required, left + 12, y - 14)
        detail("Design Pages:", bill.design_page, 330, y - 14)
        detail("Design Charge:", money(bill.design_charge), left + 12, y - 34)
        detail("Lamination:", money(bill.lamination), 330, y - 34)
        detail("Embossing:", money(bill.embossing), left + 12, y - 54)
        y -= 105

    summary = [
        ("Product Total", bill.card_total),
        ("Printing Charge", bill.printing_charge),
        ("Design Charge", bill.design_charge),
        ("Lamination", bill.lamination),
        ("Embossing", bill.embossing),
        ("Subtotal", bill.subtotal),
        ("GST (" + text(bill.gst) + "%)", bill.gst_amount),
        ("Discount", bill.discount),
        ("GRAND TOTAL", bill.final_amount)
    ]
    summary_x = 330
    for label, value in summary:
        pdf.setFont(font, 12 if label == "GRAND TOTAL" else 11)
        pdf.setFillColor(colors.HexColor("#222222"))
        pdf.drawString(summary_x, y, label)
        pdf.drawRightString(right, y, money(value))
        if label == "GRAND TOTAL":
            pdf.setFillColor(colors.HexColor("#222222"))
            pdf.rect(summary_x - 8, y - 13, right - summary_x + 8, 27, fill=1, stroke=0)
            pdf.setFillColor(colors.white)
            pdf.drawString(summary_x, y - 4, label)
            pdf.drawRightString(right, y - 4, money(value))
        y -= 25

    pdf.setStrokeColor(colors.HexColor("#dddddd"))
    pdf.line(left, 70, right, 70)
    pdf.setFont(font, 12)
    pdf.setFillColor(colors.HexColor("#222222"))
    pdf.drawCentredString(width / 2, 48, "Thank you for choosing GP Prints!")
    pdf.setFont(font, 10)
    pdf.setFillColor(colors.HexColor("#777777"))
    pdf.drawCentredString(width / 2, 34, "We appreciate your business and look forward to serving you again.")
    pdf.save()


def invoice_pdf(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    import os

    bill = get_object_or_404(Bill, id=id)
    invoice_folder = os.path.join(settings.BASE_DIR, "invoices")
    os.makedirs(invoice_folder, exist_ok=True)
    pdf_path = os.path.join(invoice_folder, bill.invoice_number + ".pdf")
    generate_invoice_pdf(bill, pdf_path)

    return FileResponse(
        open(pdf_path, "rb"),
        content_type="application/pdf"
    )


def view_invoice(request, id):
    if not request.session.get("logged_in"):
        return redirect("loginpage")

    bill = get_object_or_404(Bill, id=id)
    company_settings = CompanySettings.objects.first()
    invoice_template = {
        Bill.INVOICE_TYPE_CARDS: "invoicepage.html",
        Bill.INVOICE_TYPE_CONFIGURED_SERVICE: "configuredserviceinvoice.html",
        Bill.INVOICE_TYPE_MULTICOLOR: "multicolorinvoice.html",
    }.get(bill.invoice_type, "invoicepage.html")
    bill_data = {
        "copies": bill.total_copies,
        "paper_size": bill.paper_size,
        "printing_color": bill.printing_color,
        "printing_page": bill.printing_page,
        "printing_charge": bill.printing_charge,
        "design_required": bill.design_required,
        "design_page": bill.design_page,
        "design_charge": bill.design_charge,
        "lamination": bill.lamination,
        "embossing": bill.embossing,
        "card_total": bill.card_total,
        "subtotal": bill.subtotal,
        "gst": bill.gst,
        "gst_amount": bill.gst_amount,
        "discount": bill.discount,
        "final_amount": bill.final_amount,
        "multicolor_items": bill.multicolor_items,
    }

    return render(
        request,
        invoice_template,
        {
            "invoice_number": bill.invoice_number,
            "invoice_date": timezone.localtime(bill.created_at).strftime("%d-%m-%Y"),
            "customer": {
                "name": bill.customer_name,
                "phone": bill.customer_phone,
                "email": bill.customer_email,
                "address": bill.customer_address,
            },
            "cart": bill.products,
            "bill": bill_data,
            "company_settings": company_settings,
            "invoice_type": bill.invoice_type,
            "multicolor_items_json": json.dumps(bill.multicolor_items or []),
            "saved_invoice": True,
        },
    )

    bill = get_object_or_404(Bill, id=id)
    customer = {
        "name": bill.customer_name,
        "phone": bill.customer_phone,
        "email": bill.customer_email,
        "address": bill.customer_address
    }
    bill_data = {
        "copies": bill.total_copies,
        "paper_size": bill.paper_size,
        "printing_color": bill.printing_color,
        "printing_page": bill.printing_page,
        "printing_charge": bill.printing_charge,
        "design_required": bill.design_required,
        "design_page": bill.design_page,
        "design_charge": bill.design_charge,
        "lamination": bill.lamination,
        "embossing": bill.embossing,
        "card_total": bill.card_total,
        "subtotal": bill.subtotal,
        "gst": bill.gst,
        "gst_amount": bill.gst_amount,
        "discount": bill.discount,
        "final_amount": bill.final_amount
    }
    html = render_to_string(
        "invoicepage.html",
        {
            "invoice_number": bill.invoice_number,
            "invoice_date": timezone.localtime(
                bill.created_at
            ).strftime("%d-%m-%Y"),
            "customer": customer,
            "cart": bill.products,
            "bill": bill_data,
            "pdf_export": True
        }
    )

    def link_callback(uri, rel):
        path = finders.find(uri.replace(settings.STATIC_URL, ""))
        return path or uri

    invoice_folder = os.path.join(settings.BASE_DIR, "invoices")
    os.makedirs(invoice_folder, exist_ok=True)
    pdf_path = os.path.join(
        invoice_folder,
        bill.invoice_number + ".pdf"
    )

    html = html.replace(
        'src="/static/',
        'src="' + request.build_absolute_uri("/static/")
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(
                path=pdf_path,
                format="A4",
                print_background=True,
                margin={
                    "top": "0",
                    "right": "0",
                    "bottom": "0",
                    "left": "0"
                }
            )
            browser.close()
    except Exception:
        if not os.path.exists(pdf_path):
            raise Http404("Invoice PDF could not be generated")

    response = FileResponse(
        open(pdf_path, "rb"),
        content_type="application/pdf"
    )
    response["Cache-Control"] = "no-store"

    return response

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle
    )
    bill = get_object_or_404(Bill, id=id)
    invoice_folder = os.path.join(
        settings.BASE_DIR,
        "invoices"
    )
    os.makedirs(invoice_folder, exist_ok=True)

    pdf_path = os.path.join(
        invoice_folder,
        bill.invoice_number + ".pdf"
    )

    styles = getSampleStyleSheet()
    company_style = ParagraphStyle(
        "Company",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#222222")
    )
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        alignment=TA_RIGHT,
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#222222")
    )
    small_right = ParagraphStyle(
        "SmallRight",
        parent=styles["Normal"],
        alignment=TA_RIGHT,
        fontSize=9,
        textColor=colors.HexColor("#555555")
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#444444")
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.HexColor("#555555"),
        spaceAfter=6
    )

    def money(value):
        return "Rs. " + format(value, ",.2f")

    document = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm
    )

    invoice_date = timezone.localtime(bill.created_at).strftime(
        "%d %b %Y, %I:%M %p"
    )

    header = Table([
        [
            Paragraph("GP PRINTS", company_style),
            Paragraph("INVOICE", title_style)
        ],
        [
            Paragraph("Professional Printing Solutions", body_style),
            Paragraph(
                "Invoice No: <b>" + bill.invoice_number + "</b><br/>"
                "Date: <b>" + invoice_date + "</b>",
                small_right
            )
        ]
    ], colWidths=[95 * mm, 75 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, -1), (-1, -1), 1.5, colors.HexColor("#222222")),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 12)
    ]))

    customer_details = (
        "<b>" + bill.customer_name + "</b><br/>"
        "Phone: " + bill.customer_phone + "<br/>"
        "Email: " + (bill.customer_email or "-") + "<br/>"
        "Address: " + (bill.customer_address or "-")
    )

    details = Table([
        [
            Paragraph("BILL TO", section_style),
            Paragraph("INVOICE DETAILS", section_style)
        ],
        [
            Paragraph(customer_details, body_style),
            Paragraph(
                "Invoice No: " + bill.invoice_number + "<br/>"
                "Date: " + invoice_date + "<br/>"
                "Total Copies: " + str(bill.total_copies),
                body_style
            )
        ]
    ], colWidths=[95 * mm, 75 * mm])
    details.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5)
    ]))

    product_rows = [[
        "Model Number",
        "Card Name",
        "Qty",
        "Price",
        "Amount"
    ]]

    for item in bill.products:
        product_rows.append([
            str(item.get("model_number", "")),
            str(item.get("name", "")),
            str(item.get("quantity", 0)),
            money(float(item.get("price", 0))),
            money(float(item.get("amount", 0)))
        ])

    products = Table(
        product_rows,
        colWidths=[31 * mm, 55 * mm, 16 * mm, 29 * mm, 29 * mm],
        repeatRows=1
    )
    products.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7)
    ]))

    summary_rows = [
        ["Product Total", money(float(bill.card_total))],
        ["Printing Charge", money(float(bill.printing_charge))],
        ["Design Charge", money(float(bill.design_charge))],
        ["Lamination", money(float(bill.lamination))],
        ["Embossing", money(float(bill.embossing))],
        ["GST", money(float(bill.gst_amount))],
        ["Discount", money(float(bill.discount))],
        ["FINAL AMOUNT", money(float(bill.final_amount))]
    ]
    summary = Table(summary_rows, colWidths=[45 * mm, 45 * mm], hAlign="RIGHT")
    summary.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 12),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#222222")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#222222")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5)
    ]))

    story = [
        header,
        Spacer(1, 12),
        details,
        Spacer(1, 18),
        Paragraph("PRODUCT DETAILS", section_style),
        products,
        Spacer(1, 18),
        summary,
        Spacer(1, 25),
        Paragraph(
            "Thank you for choosing GP Prints.",
            ParagraphStyle(
                "Footer",
                parent=body_style,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#666666")
            )
        )
    ]

    document.build(story)

    response = FileResponse(
        open(pdf_path, "rb"),
        content_type="application/pdf"
    )
    response["Cache-Control"] = "no-store"

    return response


def invoice_pdf(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    bill = get_object_or_404(Bill, id=id)
    pdf_path = os.path.join(
        settings.BASE_DIR,
        "invoices",
        bill.invoice_number + ".pdf"
    )

    if not os.path.exists(pdf_path):
        raise Http404("Invoice PDF not found")

    return FileResponse(
        open(pdf_path, "rb"),
        content_type="application/pdf"
    )


# =========================
# CUSTOMER LIST
# =========================

def customer_list(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    customers = Customer.objects.all().order_by("-id")

    return render(
        request,
        "customerlist.html",
        {
            "customers": customers,
            "role": request.session.get("role")
        }
    )


# =========================
# ADD CUSTOMER
# =========================

def add_customer(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.method == "POST":

        name = request.POST.get("name")
        phone = request.POST.get("phone")
        email = request.POST.get("email")
        address = request.POST.get("address")

        Customer.objects.create(
            name=name,
            phone=phone,
            email=email,
            address=address
        )

        return redirect("customer_list")

    return render(request, "addcustomer.html")


# =========================
# EDIT CUSTOMER
# =========================

def edit_customer(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    # ONLY ADMIN
    if request.session.get("role") != "admin":
        return redirect("customer_list")

    customer = Customer.objects.get(id=id)

    if request.method == "POST":

        customer.name = request.POST.get("name")
        customer.phone = request.POST.get("phone")
        customer.email = request.POST.get("email")
        customer.address = request.POST.get("address")

        customer.save()

        return redirect("customer_list")

    return render(
        request,
        "editcustomer.html",
        {
            "customer": customer
        }
    )


# =========================
# DELETE CUSTOMER
# =========================

def delete_customer(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    # ONLY ADMIN
    if request.session.get("role") != "admin":
        return redirect("customer_list")

    customer = Customer.objects.get(id=id)

    customer.delete()

    return redirect("customer_list")


# =========================
# LOGOUT
# =========================

def logoutpage(request):

    request.session.flush()

    return redirect("loginpage")

# =========================
# PRODUCT LIST
# =========================

def product_list(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    products = Product.objects.all().order_by("-id")

    return render(
        request,
        "productlist.html",
        {
            "products": products,
            "role": request.session.get("role")
        }
    )


# =========================
# ADD PRODUCT
# =========================

def add_product(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.method == "POST":

        model_number = request.POST.get("model_number")
        name = request.POST.get("name")
        category = request.POST.get("category")
        paper_type = request.POST.get("paper_type")
        paper_size = request.POST.get("paper_size")
        print_type = request.POST.get("print_type")
        price = request.POST.get("price")
        stock = request.POST.get("stock")
        status = request.POST.get("status")
        description = request.POST.get("description")

        Product.objects.create(
            model_number=model_number,
            name=name,
            category=category,
            paper_type=paper_type,
            paper_size=paper_size,
            print_type=print_type,
            price=price,
            stock=stock,
            status=status,
            description=description
        )

        return redirect("product_list")

    return render(
        request,
        "addproduct.html"
    )


# =========================
# EDIT PRODUCT
# =========================

def edit_product(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    # ONLY ADMIN
    if request.session.get("role") != "admin":
        return redirect("product_list")

    product = Product.objects.get(id=id)

    if request.method == "POST":

        product.model_number = request.POST.get("model_number")
        product.name = request.POST.get("name")
        product.category = request.POST.get("category")
        product.paper_type = request.POST.get("paper_type")
        product.paper_size = request.POST.get("paper_size")
        product.print_type = request.POST.get("print_type")
        product.price = request.POST.get("price")
        product.stock = request.POST.get("stock")
        product.status = request.POST.get("status")
        product.description = request.POST.get("description")

        product.save()

        return redirect("product_list")

    return render(
        request,
        "editproduct.html",
        {
            "product": product
        }
    )


# =========================
# DELETE PRODUCT
# =========================

def delete_product(request, id):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    # ONLY ADMIN
    if request.session.get("role") != "admin":
        return redirect("product_list")

    product = Product.objects.get(id=id)

    product.delete()

    return redirect("product_list")

# ADD PRODUCT

def add_product(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    if request.method == "POST":

        model_number = request.POST.get("model_number")
        name = request.POST.get("name")
        category = request.POST.get("category")
        paper_type = request.POST.get("paper_type")
        paper_size = request.POST.get("paper_size")
        print_type = request.POST.get("print_type")
        price = request.POST.get("price")
        stock = request.POST.get("stock")
        status = request.POST.get("status")
        description = request.POST.get("description")

        Product.objects.create(
            model_number=model_number,
            name=name,
            category=category,
            paper_type=paper_type,
            paper_size=paper_size,
            print_type=print_type,
            price=price,
            stock=stock,
            status=status,
            description=description
        )

        return redirect("product_list")

    return render(request, "addproduct.html")

# ORDER PAGE

def order_page(request, mode=None):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    mode = mode or request.GET.get("mode")

    if mode == "cards":
        request.session["multicolor_billing"] = False
        request.session.modified = True
        return render(request, "orderpage.html")

    if mode == "multicolor":
        return redirect("multicolor_order_page")

    if mode == "services":
        request.session["multicolor_billing"] = False
        request.session.modified = True
        service_rules = list(
            PricingRule.objects.filter(active=True)
            .order_by("service", "variant", "quantity")
        )
        return render(
            request,
            "configuredserviceorder.html",
            {
                "service_rules_json": json.dumps([
                    {
                        "id": rule.id,
                        "service": rule.service,
                        "variant": rule.variant,
                        "paper_size": rule.paper_size,
                        "gsm": rule.gsm,
                        "quantity": rule.quantity,
                        "print_side": rule.print_side,
                        "price": str(rule.price),
                    }
                    for rule in service_rules
                ]),
            },
        )

    return render(
        request,
        "orderchoice.html"
    )


def multicolor_order_page(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    request.session["multicolor_billing"] = True
    request.session.modified = True

    company_settings = CompanySettings.objects.first()
    charges = (
        company_settings.multicolor_charges
        if company_settings and company_settings.multicolor_charges
        else default_multicolor_charges()
    )

    multicolor_rules = []
    side_keys = set(charges)
    has_finish_matrix = any(str(key).startswith("MC|") for key in charges)
    default_multicolor_keys = {
        key.lower()
        for key in default_multicolor_charges()
    }
    for key, price in charges.items():
        if key.startswith("MC|"):
            parts = key.split("|")
            if len(parts) != 6:
                continue
            _, paper_size, gsm, copies, side, finish = parts
            multicolor_rules.append({
                "paper_size": paper_size,
                "gsm": gsm,
                "copies": copies,
                "side": side,
                "finish": finish,
                "price": str(price),
            })
            continue

        parts = key.split("_")
        if has_finish_matrix:
            legacy_base = "_".join(parts[:3])
            if legacy_base.lower() in default_multicolor_keys:
                continue

        if len(parts) == 4:
            paper_size, gsm, copies, side = parts
            multicolor_rules.append({
                "paper_size": paper_size,
                "gsm": gsm,
                "copies": copies,
                "side": side,
                "price": str(price),
            })
            continue

        if len(parts) != 3:
            continue

        paper_size, gsm, copies = parts
        if (
            f"{paper_size}_{gsm}_{copies}_single" in side_keys
            or f"{paper_size}_{gsm}_{copies}_double" in side_keys
        ):
            continue

        multicolor_rules.append({
            "paper_size": paper_size,
            "gsm": gsm,
            "copies": copies,
            "side": "single",
            "price": str(price),
        })
        multicolor_rules.append({
            "paper_size": paper_size,
            "gsm": gsm,
            "copies": copies,
            "side": "double",
            "price": str(price),
        })

    return render(
        request,
        "multicolororder.html",
        {
            "multicolor_rules_json": json.dumps(multicolor_rules),
        }
    )


# CUSTOMER SEARCH

def search_customer(request):

    search = request.GET.get("search", "")

    customers = Customer.objects.filter(
        name__icontains=search
    )[:5]

    data = []

    for customer in customers:

        data.append({
            "id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "address": customer.address
        })

    return JsonResponse({
        "customers": data
    })


# PRODUCT SEARCH

def search_product(request):

    search = request.GET.get("search", "")

    products = Product.objects.filter(
        Q(name__icontains=search) |
        Q(model_number__icontains=search)
    )[:5]

    data = []

    for product in products:

        data.append({
            "id": product.id,
            "model_number": product.model_number,
            "name": product.name,
            "category": product.category,
            "paper_type": product.paper_type,
            "paper_size": product.paper_size,
            "print_type": product.print_type,
            "price": str(product.price),
            "stock": product.stock
        })

    return JsonResponse({
        "products": data
    })

# =========================
# BILLING PAGE
# =========================

def billing_page(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")


    import json
    from decimal import Decimal


    customer = None
    cart = []
    multicolor_items = []
    company_settings = CompanySettings.objects.first()
    printing_charges = (
        company_settings.printing_charges
        if company_settings
        else {}
    )
    design_charges = (
        company_settings.design_charges
        if company_settings
        else {}
    )

    printing_charges = {
        **default_printing_charges(),
        **printing_charges,
    }
    design_charges = {
        **default_design_charges(),
        **design_charges,
    }


    # =========================
    # DEFAULT VALUES
    # =========================

    copies = 0

    card_total = Decimal("0")

    printing_charge = Decimal("0")

    design_charge = Decimal("0")

    lamination = Decimal("0")

    embossing = Decimal("0")

    subtotal = Decimal("0")

    gst = Decimal("0")

    gst_amount = Decimal("0")

    discount = Decimal("0")

    final_amount = Decimal("0")


    paper_size = ""

    gsm = "300"

    printing_color = ""

    printing_page = ""

    design_required = "no"

    design_page = "single"


    # =========================
    # GET CUSTOMER + CART
    # FROM ORDER PAGE
    # =========================

    if request.method == "POST":

        customer_id = request.POST.get(
            "customer_id"
        )

        cart_data = request.POST.get(
            "cart"
        )

        multicolor_data = request.POST.get(
            "multicolor_items"
        )

        if not customer_id and cart_data:

            new_customer_name = request.POST.get(
                "new_customer_name",
                ""
            ).strip()

            new_customer_phone = request.POST.get(
                "new_customer_phone",
                ""
            ).strip()

            if not new_customer_name or not new_customer_phone:
                return redirect("order_page")

            customer = Customer.objects.create(
                name=new_customer_name,
                phone=new_customer_phone,
                email=request.POST.get(
                    "new_customer_email",
                    ""
                ).strip(),
                address=request.POST.get(
                    "new_customer_address",
                    ""
                ).strip()
            )

            customer_id = customer.id


        # =========================
        # ORDER PAGE -> BILLING PAGE
        # =========================

        if customer_id and cart_data:

            customer = Customer.objects.get(
                id=customer_id
            )

            try:
                cart = json.loads(cart_data)
            except (TypeError, ValueError):
                cart = []

            # Configured services must always use the current active rule from
            # Settings.  Do not trust a price sent from the browser.
            verified_cart = []
            for item in cart:
                if not isinstance(item, dict) or not item.get("rule_id"):
                    verified_cart.append(item)
                    continue

                rule = PricingRule.objects.filter(
                    id=item.get("rule_id"),
                    active=True,
                ).first()
                try:
                    quantity = int(item.get("quantity", 0) or 0)
                except (TypeError, ValueError):
                    quantity = 0
                if not rule or quantity < 1:
                    continue

                verified_cart.append({
                    "rule_id": rule.id,
                    "configured_service": True,
                    "model_number": rule.service,
                    "name": rule.variant or rule.service,
                    "category": rule.service,
                    "paper_type": f"{rule.gsm} GSM" if rule.gsm else "",
                    "paper_size": rule.paper_size,
                    "print_type": rule.print_side,
                    "price": str(rule.price),
                    # A configured price is a fixed price for the rule's
                    # selected quantity; it must never be multiplied by it.
                    "quantity": 1,
                    "selected_quantity": rule.quantity,
                })
            cart = verified_cart

            if not cart and not multicolor_data:
                return redirect("configured_service_order")

            if multicolor_data:
                try:
                    multicolor_items = json.loads(multicolor_data)
                except (TypeError, ValueError):
                    multicolor_items = []

                verified_multicolor_items = []
                for item in multicolor_items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        item_copies = int(item.get("copies", 0) or 0)
                    except (TypeError, ValueError):
                        item_copies = 0
                    configured_price = get_multicolor_price_for_bill(
                        item.get("paper_size", ""),
                        item.get("gsm", "300"),
                        item_copies,
                        company_settings,
                        item.get("side"),
                        item.get("finish"),
                    )
                    if configured_price <= 0:
                        configured_price = Decimal(str(item.get("price", "0") or "0"))
                    item["price"] = str(configured_price)
                    item["amount"] = str(configured_price)
                    verified_multicolor_items.append(item)
                multicolor_items = verified_multicolor_items


            request.session[
                "billing_customer_id"
            ] = customer.id


            request.session[
                "billing_cart"
            ] = cart

            request.session[
                "billing_multicolor_items"
            ] = multicolor_items


        # =========================
        # BILLING PAGE CALCULATE
        # =========================

        else:

            customer_id = request.session.get(
                "billing_customer_id"
            )

            cart = request.session.get(
                "billing_cart",
                []
            )

            multicolor_items = request.session.get(
                "billing_multicolor_items",
                []
            )


            if customer_id:

                customer = Customer.objects.get(
                    id=customer_id
                )


    else:

        # =========================
        # LOAD SESSION DATA
        # =========================

        customer_id = request.session.get(
            "billing_customer_id"
        )

        cart = request.session.get(
            "billing_cart",
            []
        )

        multicolor_items = request.session.get(
            "billing_multicolor_items",
            []
        )


        if customer_id:

            customer = Customer.objects.get(
                id=customer_id
            )

    if multicolor_items:
        paper_size = multicolor_items[0].get("paper_size", "")
        gsm = str(multicolor_items[0].get("gsm", "300"))

    configured_service_mode = bool(cart) and all(
        isinstance(item, dict) and item.get("configured_service")
        for item in cart
    )


    # =========================
    # PRODUCT TOTAL
    # =========================

    for item in cart:

        if item.get("type") == "multicolor":
            continue

        quantity = int(
            item.get("quantity", 0)
        )

        price = Decimal(
            str(item.get("price", 0))
        )


        amount = (
            price * quantity
        )


        item["amount"] = str(amount)


        display_quantity = int(item.get("selected_quantity", quantity) or quantity)
        item["display_quantity"] = display_quantity
        copies += display_quantity

        card_total += amount


    for item in multicolor_items:

        copies += int(item.get("copies", 0) or 0)


    # =========================
    # BILLING FORM CALCULATION
    # =========================

    # This POST is from the
    # Calculate Bill button
    if request.method == "POST" and not (
        request.POST.get("customer_id")
        and request.POST.get("cart")
    ):


        # =========================
        # PRINTING DETAILS
        # =========================

        paper_size = request.POST.get(
            "paper_size",
            ""
        )

        gsm = request.POST.get(
            "gsm",
            "300"
        )

        printing_color = request.POST.get(
            "printing_color",
            ""
        )


        printing_page = request.POST.get(
            "printing_page",
            ""
        )


        # =========================
        # PRINTING CHARGE
        # =========================

        if multicolor_items:
            printing_charge = sum(
                (
                    Decimal(str(item.get("price") or item.get("amount") or "0"))
                    for item in multicolor_items
                ),
                Decimal("0"),
            )

            first_multicolor_item = multicolor_items[0]
            paper_size = first_multicolor_item.get("paper_size", "")
            gsm = str(first_multicolor_item.get("gsm", "300"))
        elif copies > 0 and not configured_service_mode:
            multicolor_price = get_multicolor_price_for_bill(
                paper_size,
                gsm,
                copies,
                company_settings,
                printing_page,
            )

            if paper_size in {"A4", "A3"} and multicolor_price > 0:
                printing_charge = multicolor_price
            else:
                multiplier = (copies + 999) // 1000

                if paper_size == "A4":
                    if printing_color == "single" and printing_page == "single":
                        printing_charge = Decimal(
                            printing_charges.get("A4_single_single", "400")
                        ) * multiplier
                    elif printing_color == "single" and printing_page == "double":
                        printing_charge = Decimal(
                            printing_charges.get("A4_single_double", "800")
                        ) * multiplier
                    elif printing_color == "double" and printing_page == "single":
                        printing_charge = Decimal(
                            printing_charges.get("A4_double_single", "800")
                        ) * multiplier
                    elif printing_color == "double" and printing_page == "double":
                        printing_charge = Decimal(
                            printing_charges.get("A4_double_double", "800")
                        ) * multiplier

                elif paper_size == "A3":
                    if printing_color == "single" and printing_page == "single":
                        printing_charge = Decimal(
                            printing_charges.get("A3_single_single", "800")
                        ) * multiplier
                    elif printing_color == "single" and printing_page == "double":
                        printing_charge = Decimal(
                            printing_charges.get("A3_single_double", "1600")
                        ) * multiplier
                    elif printing_color == "double" and printing_page == "single":
                        printing_charge = Decimal(
                            printing_charges.get("A3_double_single", "1600")
                        ) * multiplier
                    elif printing_color == "double" and printing_page == "double":
                        printing_charge = Decimal(
                            printing_charges.get("A3_double_double", "1700")
                        ) * multiplier

                elif paper_size == "visiting":
                    printing_charge = Decimal(
                        printing_charges.get("visiting", "0")
                    )

                elif paper_size == "custom":
                    printing_charge = Decimal(
                        printing_charges.get("custom", "0")
                    )


        # =========================
        # DESIGN DETAILS
        # =========================

        design_required = "no" if configured_service_mode else request.POST.get(
            "design_required",
            "no"
        )


        design_page = "single" if configured_service_mode else request.POST.get(
            "design_page",
            "single"
        )


        if design_required == "yes":


            # A4
            if paper_size == "A4":

                if design_page == "single":

                    design_charge = Decimal(design_charges.get("A4_single", "300"))

                elif design_page == "double":

                    design_charge = Decimal(design_charges.get("A4_double", "600"))


            # A3
            elif paper_size == "A3":

                if design_page == "single":

                    design_charge = Decimal(design_charges.get("A3_single", "500"))

                elif design_page == "double":

                    design_charge = Decimal(design_charges.get("A3_double", "1000"))


            # Visiting Card
            elif paper_size == "visiting":

                design_charge = Decimal(design_charges.get("visiting", "200"))


        # =========================
        # OTHER CHARGES
        # =========================

        lamination = Decimal(
                request.POST.get("lamination")
                or (company_settings.lamination_charge if company_settings else 0)
                or "0"
        )


        embossing = Decimal(
                request.POST.get("embossing")
                or (company_settings.embossing_charge if company_settings else 0)
                or "0"
        )


        # =========================
        # GST
        # =========================

        gst = Decimal(
                request.POST.get("gst")
                or (company_settings.default_gst if company_settings else 0)
                or "0"
        )


        # =========================
        # DISCOUNT
        # =========================

        discount = Decimal(
            request.POST.get(
                "discount"
            ) or "0"
        )


        # =========================
        # SUBTOTAL
        # =========================

        subtotal = (

            card_total

            + printing_charge

            + design_charge

            + lamination

            + embossing

        )


        # =========================
        # GST AMOUNT
        # =========================

        gst_amount = (
            subtotal
            * gst
            / Decimal("100")
        )


        # =========================
        # FINAL AMOUNT
        # =========================

        final_amount = (
            subtotal
            + gst_amount
            - discount
        )


        # Prevent negative bill
        if final_amount < 0:

            final_amount = Decimal("0")

        request.session["calculated_bill"] = {
            "copies": copies,
            "card_total": str(card_total),
            "printing_charge": str(printing_charge),
            "design_charge": str(design_charge),
            "lamination": str(lamination),
            "embossing": str(embossing),
            "subtotal": str(subtotal),
            "gst": str(gst),
            "gst_amount": str(gst_amount),
            "discount": str(discount),
            "final_amount": str(final_amount),
            "paper_size": paper_size,
            "gsm": gsm,
            "printing_color": printing_color,
            "printing_page": printing_page,
            "design_required": design_required,
            "design_page": design_page,
            "multicolor_items": multicolor_items,
        }
        request.session.modified = True

        if request.POST.get("next") == "invoice":
            return redirect("invoice_page")


    # =========================
    # RENDER BILLING PAGE
    # =========================

    return render(
        request,
        "multicolorbilling.html" if request.session.get("multicolor_billing") else "billingpage.html",
        {

            "customer": customer,

            "cart": cart,
            "multicolor_items": multicolor_items,

            "copies": copies,

            "card_total": card_total,

            "printing_charge":
                printing_charge,

            "design_charge":
                design_charge,

            "lamination":
                lamination,

            "embossing":
                embossing,

            "subtotal":
                subtotal,

            "gst":
                gst,

            "gst_amount":
                gst_amount,

            "discount":
                discount,

            "final_amount":
                final_amount,

            "paper_size":
                paper_size,

            "printing_color":
                printing_color,

            "printing_page":
                printing_page,

            "design_required":
                design_required,

            "design_page":
                design_page

            ,
            "configured_service_mode": configured_service_mode,
            "printing_charges": printing_charges,
            "design_charges": design_charges,
            "multicolor_mode": request.session.get("multicolor_billing", False),

        }
    )


def multicolor_billing_page(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    request.session["multicolor_billing"] = True
    request.session.modified = True

    return billing_page(request)

def invoice_page(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    customer_id = request.session.get(
        "billing_customer_id"
    )

    if not customer_id:
        return redirect("order_page")

    customer = Customer.objects.get(
        id=customer_id
    )

    cart = request.session.get(
        "billing_cart",
        []
    )

    bill = request.session.get(
        "calculated_bill"
    )

    if not bill:
        return redirect("billing_page")

    import uuid
    from django.utils import timezone

    company_settings = CompanySettings.objects.first()

    invoice_number = (
        (company_settings.invoice_prefix if company_settings else "GP-")
        + uuid.uuid4().hex[:8].upper()
    )

    invoice_date = timezone.localtime().strftime("%d-%m-%Y")

    invoice_type = (
        "multicolor"
        if request.session.get("multicolor_billing") or bill.get("multicolor_items")
        else "configured_service"
        if any(item.get("configured_service") or item.get("rule_id") for item in cart)
        else "cards"
    )
    invoice_template = {
        "cards": "invoicepage.html",
        "configured_service": "configuredserviceinvoice.html",
        "multicolor": "multicolorinvoice.html",
    }[invoice_type]

    return render(
        request,
        invoice_template,
        {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "customer": customer,
            "cart": cart,
            "bill": bill,
            "company_settings": company_settings,
            "invoice_type": invoice_type,
            "multicolor_items_json": json.dumps(
                bill.get("multicolor_items", [])
            ),
        }
    )
# =========================
# SAVE INVOICE
# =========================

def save_invoice(request):

    if not request.session.get("logged_in"):
        return redirect("loginpage")

    from decimal import Decimal
    from django.conf import settings
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    import os


    if request.method != "POST":

        return redirect("invoice_page")

    import json

    # =========================
    # CUSTOMER
    # =========================

    customer_id = request.session.get(
        "billing_customer_id"
    )

    if not customer_id:

        return redirect("order_page")


    customer = Customer.objects.get(
        id=customer_id
    )


    # =========================
    # CART
    # =========================

    cart = request.session.get(
        "billing_cart",
        []
    )


    # =========================
    # CALCULATED BILL
    # =========================

    bill_data = request.session.get(
        "calculated_bill"
    )


    if not bill_data:

        return redirect("billing_page")


    # =========================
    # INVOICE NUMBER
    # =========================

    invoice_number = request.POST.get(
        "invoice_number"
    )


    # =========================
    # PRODUCTS
    # =========================

    products = []


    for item in cart:

        products.append({

            "model_number":
                item.get(
                    "model_number",
                    ""
                ),

            "name":
                item.get(
                    "name",
                    ""
                ),

            "category":
                item.get(
                    "category",
                    ""
                ),

            "paper_type":
                item.get(
                    "paper_type",
                    ""
                ),

            "paper_size":
                item.get(
                    "paper_size",
                    ""
                ),

            "print_type":
                item.get(
                    "print_type",
                    ""
                ),

            "quantity":
                int(
                    item.get(
                        "display_quantity",
                        item.get("selected_quantity", item.get("quantity", 0))
                    )
                ),

            "price":
                str(
                    item.get(
                        "price",
                        "0"
                    )
                ),

            "amount":
                str(
                    item.get(
                        "amount",
                        "0"
                    )
                )

        })


    # =========================
    # MULTICOLOR ITEMS
    # =========================

    multicolor_items = []
    multicolor_raw = request.POST.get("multicolor_items")

    if multicolor_raw:
        try:
            multicolor_items = json.loads(multicolor_raw)
        except (TypeError, ValueError):
            multicolor_items = []

    invoice_type = (
        Bill.INVOICE_TYPE_MULTICOLOR
        if multicolor_items or request.session.get("multicolor_billing")
        else Bill.INVOICE_TYPE_CONFIGURED_SERVICE
        if any(item.get("configured_service") or item.get("rule_id") for item in cart)
        else Bill.INVOICE_TYPE_CARDS
    )


    # =========================
    # SAVE BILL IN DATABASE
    # =========================

    bill = Bill.objects.create(

        invoice_number=
            invoice_number,

        invoice_type=invoice_type,

        customer_name=
            customer.name,

        customer_phone=
            customer.phone,

        customer_email=
            customer.email,

        customer_address=
            customer.address,

        products=
            products,

        multicolor_items=
            multicolor_items,

        total_copies=
            int(
                bill_data.get(
                    "copies",
                    0
                )
            ),

        paper_size=
            bill_data.get(
                "paper_size",
                ""
            ),

        printing_color=
            bill_data.get(
                "printing_color",
                ""
            ),

        printing_page=
            bill_data.get(
                "printing_page",
                ""
            ),

        printing_charge=
            Decimal(
                bill_data.get(
                    "printing_charge",
                    "0"
                )
            ),

        design_required=
            bill_data.get(
                "design_required",
                "no"
            ),

        design_page=
            bill_data.get(
                "design_page",
                ""
            ),

        design_charge=
            Decimal(
                bill_data.get(
                    "design_charge",
                    "0"
                )
            ),

        lamination=
            Decimal(
                bill_data.get(
                    "lamination",
                    "0"
                )
            ),

        embossing=
            Decimal(
                bill_data.get(
                    "embossing",
                    "0"
                )
            ),

        other_charges=Decimal("0"),

        card_total=
            Decimal(
                bill_data.get(
                    "card_total",
                    "0"
                )
            ),

        subtotal=
            Decimal(
                bill_data.get(
                    "subtotal",
                    "0"
                )
            ),

        gst=
            Decimal(
                bill_data.get(
                    "gst",
                    "0"
                )
            ),

        gst_amount=
            Decimal(
                bill_data.get(
                    "gst_amount",
                    "0"
                )
            ),

        discount=
            Decimal(
                bill_data.get(
                    "discount",
                    "0"
                )
            ),

        final_amount=
            Decimal(
                bill_data.get(
                    "final_amount",
                    "0"
                )
            )

    )

    request.session.pop("billing_customer_id", None)
    request.session.pop("billing_cart", None)
    request.session.pop("calculated_bill", None)

    return render(
        request,
        "invoicesaved.html",
        {
            "bill": bill
        }
    )


    # =========================
    # CREATE INVOICE FOLDER
    # =========================

    invoice_folder = os.path.join(
        settings.BASE_DIR,
        "invoices"
    )


    os.makedirs(
        invoice_folder,
        exist_ok=True
    )


    # =========================
    # PDF PATH
    # =========================

    pdf_path = os.path.join(

        invoice_folder,

        invoice_number + ".pdf"

    )


    # =========================
    # CREATE PDF
    # =========================

    pdf = canvas.Canvas(
        pdf_path,
        pagesize=A4
    )


    width, height = A4


    y = height - 50


    # =========================
    # COMPANY HEADER
    # =========================

    pdf.setFont(
        "Helvetica-Bold",
        24
    )

    pdf.drawString(
        50,
        y,
        "GP PRINTS"
    )


    pdf.setFont(
        "Helvetica",
        11
    )

    pdf.drawString(
        50,
        y - 20,
        "Printing & Invitation Solutions"
    )


    pdf.setFont(
        "Helvetica-Bold",
        18
    )

    pdf.drawRightString(
        width - 50,
        y,
        "INVOICE"
    )


    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawRightString(
        width - 50,
        y - 20,
        "Invoice No: "
        + invoice_number
    )


    pdf.drawRightString(
        width - 50,
        y - 35,
        "Customer: "
        + customer.name
    )


    y -= 80


    # =========================
    # CUSTOMER DETAILS
    # =========================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Customer Details"
    )


    y -= 20


    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        "Name: " + customer.name
    )

    y -= 15

    pdf.drawString(
        50,
        y,
        "Phone: " + customer.phone
    )

    y -= 15

    pdf.drawString(
        50,
        y,
        "Email: "
        + (customer.email or "-")
    )

    y -= 30


    # =========================
    # PRODUCTS
    # =========================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Product Details"
    )


    y -= 20


    pdf.setFont(
        "Helvetica",
        9
    )


    for item in products:

        text = (
            item["model_number"]
            + " | "
            + item["name"]
            + " | Qty: "
            + str(item["quantity"])
            + " | ₹"
            + item["amount"]
        )


        pdf.drawString(
            50,
            y,
            text[:100]
        )


        y -= 15


        if y < 100:

            pdf.showPage()

            y = height - 50

            pdf.setFont(
                "Helvetica",
                9
            )


    y -= 15


    # =========================
    # BILL DETAILS
    # =========================

    pdf.setFont(
        "Helvetica-Bold",
        12
    )

    pdf.drawString(
        50,
        y,
        "Bill Details"
    )


    y -= 20


    pdf.setFont(
        "Helvetica",
        10
    )


    details = [

        (
            "Product Total",
            bill_data["card_total"]
        ),

        (
            "Printing Charge",
            bill_data["printing_charge"]
        ),

        (
            "Design Charge",
            bill_data["design_charge"]
        ),

        (
            "Lamination",
            bill_data["lamination"]
        ),

        (
            "Embossing",
            bill_data["embossing"]
        ),

        (
            "Subtotal",
            bill_data["subtotal"]
        ),

        (
            "GST",
            bill_data["gst_amount"]
        ),

        (
            "Discount",
            bill_data["discount"]
        )

    ]


    for label, value in details:

        pdf.drawString(
            50,
            y,
            label
        )

        pdf.drawRightString(
            width - 50,
            y,
            "₹" + value
        )

        y -= 18


    # =========================
    # FINAL AMOUNT
    # =========================

    y -= 10


    pdf.setFont(
        "Helvetica-Bold",
        14
    )

    pdf.drawString(
        50,
        y,
        "FINAL AMOUNT"
    )


    pdf.drawRightString(
        width - 50,
        y,
        "₹"
        + bill_data["final_amount"]
    )


    # =========================
    # SAVE PDF
    # =========================

    pdf.save()

    # =========================
    # CLEAR SESSION
    # =========================

    request.session.pop(
        "billing_customer_id",
        None
    )

    request.session.pop(
        "billing_cart",
        None
    )

    request.session.pop(
        "calculated_bill",
        None
    )


    # =========================
    # SUCCESS PAGE
    # =========================

    return render(

        request,

        "invoicesaved.html",

        {
            "bill": bill
        }

    )

#new customer
def save_new_customer(request):

    if not request.session.get("logged_in"):
        return JsonResponse({
            "success": False,
            "message": "Please login first."
        })

    if request.method == "POST":

        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        address = request.POST.get("address", "").strip()

        if not name or not phone:
            return JsonResponse({
                "success": False,
                "message": "Name and phone are required."
            })

        customer = Customer.objects.create(
            name=name,
            phone=phone,
            email=email,
            address=address
        )

        return JsonResponse({
            "success": True,
            "customer": {
                "id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "email": customer.email,
                "address": customer.address
            }
        })

    return JsonResponse({
        "success": False,
        "message": "Invalid request."
    })
