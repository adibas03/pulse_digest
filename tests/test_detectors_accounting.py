# tests/test_detectors_accounting.py
"""Tests for the three accounting detectors: overdue_invoices,
payment_delay_outlier, credit_limit_breach.

Uses AccountTestInvoicingCommon for a minimal working chart of accounts.
This is the most environment-sensitive file in the suite (exact account/
journal field names on AccountTestInvoicingCommon have shifted slightly
across Odoo versions) — expect to adjust fixture details for your build.
"""
from dateutil.relativedelta import relativedelta

from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged

from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.base import Scope
from odoo.addons.pulse_digest.models.detectors.account.overdue_invoices import (
    OverdueInvoicesDetector,
)
from odoo.addons.pulse_digest.models.detectors.account.credit_limit_breach import (
    CreditLimitBreachDetector,
)
from odoo.addons.pulse_digest.models.detectors.account.payment_delay_outlier import (
    PaymentDelayOutlierDetector,
)


@tagged("post_install", "-at_install")
class AccountingDetectorCase(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope_company = Scope.company(cls.company_data["company"])

    def setUp(self):
        super().setUp()
        # Use Odoo's own "today" consistently, matching what the detectors
        # themselves call (fields.Date.context_today), rather than mixing in
        # datetime.date.today().
        from odoo import fields as odoo_fields
        self.today = odoo_fields.Date.context_today(self.env.user)

    def _make_invoice(self, partner, invoice_date, due_date, amount=100.0,
                       salesperson=None, post=True):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_date": invoice_date,
            "invoice_date_due": due_date,
            "invoice_user_id": salesperson.id if salesperson else False,
            "invoice_line_ids": [(0, 0, {
                "name": "Test line",
                "quantity": 1,
                "price_unit": amount,
                "account_id": self.company_data["default_account_revenue"].id,
            })],
        })
        if post:
            move.action_post()
        return move

    def _pay_invoice(self, move):
        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": move.partner_id.id,
            "amount": move.amount_total,
            "journal_id": self.company_data["default_journal_bank"].id,
            "date": move.invoice_date_due,
        })
        payment.action_post()
        (move.line_ids + payment.move_id.line_ids).filtered(
            lambda l: l.account_id == move.line_ids.mapped("account_id")[:1]
            and not l.reconciled
        ).reconcile()
        return payment


class TestOverdueInvoicesDetector(AccountingDetectorCase):

    def test_overdue_invoice_is_flagged(self):
        move = self._make_invoice(
            self.partner_a,
            invoice_date=self.today - relativedelta(days=40),
            due_date=self.today - relativedelta(days=35),
        )
        detector = OverdueInvoicesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(move.id, [f.res_id for f in findings])

    def test_not_yet_due_invoice_not_flagged(self):
        move = self._make_invoice(
            self.partner_a,
            invoice_date=self.today,
            due_date=self.today + relativedelta(days=30),
        )
        detector = OverdueInvoicesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(move.id, [f.res_id for f in findings])

    def test_paid_invoice_not_flagged(self):
        move = self._make_invoice(
            self.partner_a,
            invoice_date=self.today - relativedelta(days=40),
            due_date=self.today - relativedelta(days=35),
        )
        self._pay_invoice(move)
        detector = OverdueInvoicesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(move.id, [f.res_id for f in findings])

    def test_severity_buckets(self):
        overdue_low = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=30),
            due_date=self.today - relativedelta(days=20))
        overdue_warning = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=50),
            due_date=self.today - relativedelta(days=45))
        overdue_critical = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=80),
            due_date=self.today - relativedelta(days=70))

        detector = OverdueInvoicesDetector()
        by_id = {f.res_id: f
                 for f in detector.compute(self.env, self.scope_company)}

        self.assertEqual(by_id[overdue_low.id].severity, SEVERITY_INFO)
        self.assertEqual(by_id[overdue_warning.id].severity, SEVERITY_WARNING)
        self.assertEqual(by_id[overdue_critical.id].severity, SEVERITY_CRITICAL)

    def test_user_scope_filters_to_assigned_salesperson(self):
        salesperson = self.env.ref("base.user_admin")
        mine = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=40),
            due_date=self.today - relativedelta(days=35),
            salesperson=salesperson)
        not_mine = self._make_invoice(
            self.partner_b, invoice_date=self.today - relativedelta(days=40),
            due_date=self.today - relativedelta(days=35),
            salesperson=False)

        detector = OverdueInvoicesDetector()
        scope = Scope.user(salesperson)
        ids = [f.res_id for f in detector.compute(self.env, scope)]
        self.assertIn(mine.id, ids)
        self.assertNotIn(not_mine.id, ids)

    def test_min_amount_param_filters_small_invoices(self):
        move = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=40),
            due_date=self.today - relativedelta(days=35), amount=5.0)
        detector = OverdueInvoicesDetector(params={"min_amount": 100.0})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(move.id, [f.res_id for f in findings])

    def test_min_days_overdue_param(self):
        move = self._make_invoice(
            self.partner_a, invoice_date=self.today - relativedelta(days=5),
            due_date=self.today - relativedelta(days=2))
        detector = OverdueInvoicesDetector(params={"min_days_overdue": 10})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(move.id, [f.res_id for f in findings])


class TestCreditLimitBreachDetector(AccountingDetectorCase):

    def test_partner_over_limit_is_flagged(self):
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 50.0,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(self.partner_a.id, [f.res_id for f in findings])

    def test_partner_under_limit_not_flagged(self):
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 5000.0,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(self.partner_a.id, [f.res_id for f in findings])

    def test_min_breach_amount_skips_rounding_noise(self):
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 199.99,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector(params={"min_breach_amount": 1.0})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(self.partner_a.id, [f.res_id for f in findings])

    def test_severity_thresholds(self):
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 100.0,
        })
        # 30% over -> critical (threshold 0.25)
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=130.0)

        detector = CreditLimitBreachDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        finding = next(f for f in findings if f.res_id == self.partner_a.id)
        self.assertEqual(finding.severity, SEVERITY_CRITICAL)

    def test_no_salesperson_excluded_from_per_user_digest(self):
        # Deliberate v1 gap, documented on the detector: a partner with no
        # assigned salesperson never appears in a per-user run, only in the
        # company-wide one.
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 50.0,
            "user_id": False,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector()
        company_findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(self.partner_a.id, [f.res_id for f in company_findings])

        user_findings = list(detector.compute(
            self.env, Scope.user(self.env.ref("base.user_admin"))))
        self.assertNotIn(self.partner_a.id, [f.res_id for f in user_findings])

    def test_assigned_salesperson_included_in_per_user_digest(self):
        salesperson = self.env.ref("base.user_admin")
        self.partner_a.write({
            "use_partner_credit_limit": True,
            "credit_limit": 50.0,
            "user_id": salesperson.id,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector()
        user_findings = list(detector.compute(self.env, Scope.user(salesperson)))
        self.assertIn(self.partner_a.id, [f.res_id for f in user_findings])

    def test_with_company_scoping_does_not_cross_contaminate(self):
        # Same partner, different credit_limit per company (company_dependent
        # field) — a breach in company A shouldn't leak into company B's scope.
        company_b = self.company_data_2["company"] if hasattr(
            self, "company_data_2") else None
        if not company_b:
            self.skipTest("second company fixture not available in this "
                           "AccountTestInvoicingCommon setup")
        self.partner_a.with_company(self.company_data["company"]).write({
            "use_partner_credit_limit": True, "credit_limit": 50.0,
        })
        self.partner_a.with_company(company_b).write({
            "use_partner_credit_limit": True, "credit_limit": 5000.0,
        })
        self._make_invoice(
            self.partner_a, invoice_date=self.today, due_date=self.today,
            amount=200.0)

        detector = CreditLimitBreachDetector()
        findings_a = list(detector.compute(self.env, self.scope_company))
        findings_b = list(detector.compute(self.env, Scope.company(company_b)))
        self.assertIn(self.partner_a.id, [f.res_id for f in findings_a])
        self.assertNotIn(self.partner_a.id, [f.res_id for f in findings_b])


class TestPaymentDelayOutlierDetector(AccountingDetectorCase):

    def _make_paid_invoice(self, days_late, invoice_offset_days):
        move = self._make_invoice(
            self.partner_a,
            invoice_date=self.today - relativedelta(days=invoice_offset_days),
            due_date=self.today - relativedelta(days=invoice_offset_days - 10),
        )
        payment = self._pay_invoice(move)
        # Backdate the payment to control days-to-pay precisely.
        paid_date = move.invoice_date_due + relativedelta(days=days_late)
        payment.write({"date": paid_date})
        return move

    def test_insufficient_baseline_produces_no_findings(self):
        # Only 2 prior payments, min_payments_for_baseline defaults to 4.
        self._make_paid_invoice(days_late=2, invoice_offset_days=60)
        self._make_paid_invoice(days_late=1, invoice_offset_days=50)
        self._make_paid_invoice(days_late=20, invoice_offset_days=5)

        detector = PaymentDelayOutlierDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertEqual(findings, [])

    def test_outlier_delay_flagged_against_baseline(self):
        for offset, delay in [(60, 1), (50, 2), (40, 1), (30, 2)]:
            self._make_paid_invoice(days_late=delay, invoice_offset_days=offset)
        # Latest payment: dramatically later than the ~1.5-day baseline.
        self._make_paid_invoice(days_late=20, invoice_offset_days=5)

        detector = PaymentDelayOutlierDetector(
            params={"min_payments_for_baseline": 4})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertTrue(
            any(f.res_id == self.partner_a.id for f in findings),
            "expected the outlier partner to be flagged")

    def test_consistent_payer_not_flagged(self):
        for offset in (60, 50, 40, 30, 20):
            self._make_paid_invoice(days_late=2, invoice_offset_days=offset)

        detector = PaymentDelayOutlierDetector(
            params={"min_payments_for_baseline": 4})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertFalse(
            any(f.res_id == self.partner_a.id for f in findings),
            "a consistently-on-time payer should not be flagged")
