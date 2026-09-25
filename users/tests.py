from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password

from users.models import Bill, CompanySettings, EmailVerification, PricingRule
from users.views import get_multicolor_price_for_bill


class BillMulticolorStorageTests(TestCase):
    def test_bill_can_store_multicolor_items_in_json(self):
        bill = Bill.objects.create(
            invoice_number="GP-TEST-001",
            customer_name="Test Customer",
            customer_phone="9999999999",
            products=[
                {
                    "model_number": "CARD-1",
                    "name": "Visiting Card",
                    "quantity": 500,
                    "price": "2.00",
                    "amount": "1000.00",
                }
            ],
            multicolor_items=[
                {
                    "paper_size": "A4",
                    "gsm": 300,
                    "copies": 500,
                    "price": "5600.00",
                    "amount": "5600.00",
                }
            ],
            total_copies=1000,
            card_total=Decimal("1000.00"),
            printing_charge=Decimal("5600.00"),
            subtotal=Decimal("6600.00"),
            gst=Decimal("18.00"),
            gst_amount=Decimal("1188.00"),
            final_amount=Decimal("7788.00"),
        )

        self.assertEqual(bill.multicolor_items[0]["paper_size"], "A4")
        self.assertEqual(str(bill.final_amount), "7788.00")


class CompanySettingsMulticolorPricingTests(TestCase):
    def test_multicolor_pricing_can_be_stored_in_company_settings(self):
        settings_record = CompanySettings.objects.create(
            company_name="GP Prints",
            multicolor_charges={
                "A4_300_500": "5600",
                "A4_300_1000": "7800",
            },
        )

        self.assertEqual(settings_record.multicolor_charges["A4_300_500"], "5600")
        self.assertEqual(settings_record.multicolor_charges["A4_300_1000"], "7800")

    def test_multicolor_price_lookup_uses_company_settings_value(self):
        settings_record = CompanySettings.objects.create(
            company_name="GP Prints",
            multicolor_charges={
                "A4_300_500": "5600",
                "A4_300_1000": "7800",
            },
        )

        self.assertEqual(
            get_multicolor_price_for_bill("A4", "300", 500, settings_record),
            Decimal("5600"),
        )
        self.assertEqual(
            get_multicolor_price_for_bill("A4", "300", 800, settings_record),
            Decimal("7800"),
        )

    def test_multicolor_price_lookup_respects_single_vs_double_side(self):
        settings_record = CompanySettings.objects.create(
            company_name="GP Prints",
            multicolor_charges={
                "A4_300_500": "5600",
                "A4_300_500_double": "6200",
            },
        )

        self.assertEqual(
            get_multicolor_price_for_bill("A4", "300", 500, settings_record, "single"),
            Decimal("5600"),
        )
        self.assertEqual(
            get_multicolor_price_for_bill("A4", "300", 500, settings_record, "double"),
            Decimal("6200"),
        )


class SettingsMulticolorPricingTests(TestCase):
    def setUp(self):
        session = self.client.session
        session["logged_in"] = True
        session["username"] = "admin"
        session["role"] = "admin"
        session.save()

    def test_settings_page_renders_multicolor_rate_editor(self):
        response = self.client.get("/settings/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Multicolor Printing Rates")
        self.assertContains(response, "multicolor-paper-sizes")
        self.assertContains(response, "new_multicolor_1_paper_size")

    def test_settings_saves_edited_and_new_multicolor_rates(self):
        settings_response = self.client.get("/settings/")
        rates = settings_response.context["multicolor_rate_fields"]
        data = {}

        for index, rate in enumerate(rates):
            prefix = f"multicolor_rate_{index}_"
            data[f"{prefix}paper_size"] = rate["paper_size"]
            data[f"{prefix}gsm"] = rate["gsm"]
            data[f"{prefix}copies"] = rate["copies"]
            data[f"{prefix}price"] = rate["value"]

        data.update({
            "new_multicolor_1_paper_size": "A5",
            "new_multicolor_1_gsm": "250",
            "new_multicolor_1_copies": "750",
            "new_multicolor_1_price": "1234.50",
        })
        edited_rate_index = next(
            index for index, rate in enumerate(rates)
            if rate["key"] == "A4_300_500"
        )
        data[f"multicolor_rate_{edited_rate_index}_price"] = "9999"

        response = self.client.post("/settings/", data)

        self.assertEqual(response.status_code, 302)
        settings_record = CompanySettings.objects.get(id=1)
        self.assertEqual(
            settings_record.multicolor_charges["A4_300_500"],
            "9999",
        )
        self.assertEqual(
            settings_record.multicolor_charges["A5_250_750"],
            "1234.50",
        )

        order_response = self.client.get("/orders/multicolor/")
        self.assertContains(order_response, '"paper_size": "A5"')
        self.assertContains(order_response, '"gsm": "250"')
        self.assertContains(order_response, '"copies": "750"')

    def test_admin_can_create_new_pricing_rule_from_settings_add_field_form(self):
        response = self.client.post(
            "/settings/add-field/",
            {
                "service": "Visiting Card",
                "variant": "Premium Card",
                "paper_size": "Custom",
                "gsm": "300",
                "quantity": "500",
                "print_side": "S/S",
                "price": "1200",
                "description": "Premium visiting card",
                "active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            PricingRule.objects.filter(
                service="Visiting Card",
                variant="Premium Card",
                paper_size="Custom",
                gsm="300",
                quantity=500,
                print_side="S/S",
            ).exists()
        )

    def test_staff_can_view_settings_but_cannot_create_new_pricing_rule(self):
        session = self.client.session
        session["logged_in"] = True
        session["username"] = "staff"
        session["role"] = "staff"
        session.save()

        response = self.client.get("/settings/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View-only access")

        add_response = self.client.post(
            "/settings/add-field/",
            {
                "service": "Visiting Card",
                "variant": "Staff Card",
                "price": "1500",
            },
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertFalse(
            PricingRule.objects.filter(
                variant="Staff Card",
            ).exists()
        )


class UserAccountEmailSettingsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.get(username="admin")
        self.staff = User.objects.get(username="staff")
        session = self.client.session
        session["logged_in"] = True
        session["username"] = "admin"
        session["role"] = "admin"
        session.save()

    def test_settings_shows_auth_accounts(self):
        response = self.client.get("/settings/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User Account Settings")
        self.assertContains(response, self.admin.username)
        self.assertContains(response, self.staff.username)

    @patch("users.views.send_mail")
    @patch("users.views.secrets.randbelow", return_value=123456)
    def test_admin_can_verify_staff_email_change(self, mocked_random, mocked_send_mail):
        response = self.client.post(
            "/settings/request-email-change/",
            {"user_id": self.staff.id, "new_email": "staff@example.com"},
        )

        self.assertEqual(response.status_code, 302)
        verification = EmailVerification.objects.get(user=self.staff, used=False)
        self.assertTrue(check_password("123456", verification.code_hash))
        mocked_send_mail.assert_called_once()

        self.client.post(
            "/settings/verify-email-change/",
            {"verification_code": "123456"},
        )
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.email, "staff@example.com")
        self.assertTrue(EmailVerification.objects.get(id=verification.id).used)

    def test_staff_cannot_start_admin_email_change(self):
        session = self.client.session
        session["username"] = "staff"
        session["role"] = "staff"
        session.save()

        response = self.client.post(
            "/settings/request-email-change/",
            {"user_id": self.admin.id, "new_email": "blocked@example.com"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            EmailVerification.objects.filter(
                user=self.admin,
                new_email="blocked@example.com",
            ).exists()
        )

