# tests/test_detectors_sales.py
"""Tests for the three sales/CRM detectors: stale_opportunities,
deals_closing_today, deal_velocity_drop.
"""
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.tests.common import TransactionCase

from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.base import Scope
from odoo.addons.pulse_digest.models.detectors.sale.stale_opportunities import (
    StaleOpportunitiesDetector,
)
from odoo.addons.pulse_digest.models.detectors.sale.deals_closing_today import (
    DealsClosingTodayDetector,
)
from odoo.addons.pulse_digest.models.detectors.sale.deal_velocity_drop import (
    DealVelocityDropDetector,
)


class SalesDetectorCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.scope_company = Scope.company(cls.env.company)
        cls.partner = cls.env["res.partner"].create(
            {"name": "Sales Test Partner"})
        cls.open_stage = cls.env["crm.stage"].create(
            {"name": "Open Test Stage", "is_won": False})
        cls.won_stage = cls.env["crm.stage"].create(
            {"name": "Won Test Stage", "is_won": True})

    def setUp(self):
        super().setUp()
        self.today = fields.Date.context_today(self.env.user)

    def _make_lead(self, date_last_stage_update, date_deadline=None,
                   expected_revenue=1000.0, user_id=None, stage=None,
                   active=True):
        return self.env["crm.lead"].create({
            "name": "Test Opportunity",
            "type": "opportunity",
            "partner_id": self.partner.id,
            "company_id": self.env.company.id,
            "stage_id": (stage or self.open_stage).id,
            "date_last_stage_update": date_last_stage_update,
            "date_deadline": date_deadline,
            "expected_revenue": expected_revenue,
            "user_id": user_id.id if user_id else False,
            "active": active,
        })


class TestStaleOpportunitiesDetector(SalesDetectorCase):

    def test_stale_opportunity_is_flagged(self):
        lead = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20))
        detector = StaleOpportunitiesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(lead.id, [f.res_id for f in findings])

    def test_recently_touched_opportunity_not_flagged(self):
        lead = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=2))
        detector = StaleOpportunitiesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])

    def test_won_opportunity_excluded(self):
        lead = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20),
            stage=self.won_stage)
        detector = StaleOpportunitiesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])

    def test_archived_lead_excluded(self):
        lead = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20),
            active=False)
        detector = StaleOpportunitiesDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])

    def test_severity_buckets(self):
        warn_threshold = StaleOpportunitiesDetector.DEFAULT_PARAMS["severity_thresholds"].get(
            SEVERITY_WARNING)
        crit_threshold = StaleOpportunitiesDetector.DEFAULT_PARAMS["severity_thresholds"].get(
            SEVERITY_CRITICAL)
        low = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=warn_threshold-1))
        warning = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=warn_threshold + 5))
        critical = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=crit_threshold + 10))

        detector = StaleOpportunitiesDetector()
        by_id = {f.res_id: f
                 for f in detector.compute(self.env, self.scope_company)}
        self.assertEqual(by_id[low.id].severity, SEVERITY_INFO)
        self.assertEqual(by_id[warning.id].severity, SEVERITY_WARNING)
        self.assertEqual(by_id[critical.id].severity, SEVERITY_CRITICAL)

    def test_user_scope_filters_to_assigned_salesperson(self):
        salesperson = self.env.ref("base.user_admin")
        mine = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20),
            user_id=salesperson)
        not_mine = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20),
            user_id=False)

        detector = StaleOpportunitiesDetector()
        ids = [f.res_id for f in
               detector.compute(self.env, Scope.user(salesperson))]
        self.assertIn(mine.id, ids)
        self.assertNotIn(not_mine.id, ids)

    def test_min_expected_revenue_param(self):
        lead = self._make_lead(
            date_last_stage_update=self.today - relativedelta(days=20),
            expected_revenue=10.0)
        detector = StaleOpportunitiesDetector(
            params={"min_expected_revenue": 100.0})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])


class TestDealsClosingTodayDetector(SalesDetectorCase):

    def test_deal_closing_today_is_flagged(self):
        lead = self._make_lead(
            date_last_stage_update=self.today, date_deadline=self.today)
        detector = DealsClosingTodayDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(lead.id, [f.res_id for f in findings])

    def test_deal_closing_in_future_not_flagged_by_default(self):
        lead = self._make_lead(
            date_last_stage_update=self.today,
            date_deadline=self.today + relativedelta(days=5))
        detector = DealsClosingTodayDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])

    def test_horizon_days_param_extends_window(self):
        lead = self._make_lead(
            date_last_stage_update=self.today,
            date_deadline=self.today + relativedelta(days=3))
        detector = DealsClosingTodayDetector(params={"horizon_days": 5})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertIn(lead.id, [f.res_id for f in findings])

    def test_past_deadline_not_flagged(self):
        lead = self._make_lead(
            date_last_stage_update=self.today,
            date_deadline=self.today - relativedelta(days=2))
        detector = DealsClosingTodayDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])

    def test_won_deal_excluded(self):
        lead = self._make_lead(
            date_last_stage_update=self.today, date_deadline=self.today,
            stage=self.won_stage)
        detector = DealsClosingTodayDetector()
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertNotIn(lead.id, [f.res_id for f in findings])


class TestDealVelocityDropDetector(SalesDetectorCase):

    def _touch(self, user, weeks_ago):
        self._make_lead(
            date_last_stage_update=self.today -
            relativedelta(weeks=weeks_ago),
            user_id=user)

    def test_insufficient_baseline_produces_no_findings(self):
        salesperson = self.env.ref("base.user_admin")
        self._touch(salesperson, 0)
        self._touch(salesperson, 1)
        detector = DealVelocityDropDetector(
            params={"min_weeks_for_baseline": 4})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertEqual(findings, [])

    def test_velocity_drop_flagged(self):
        salesperson = self.env.ref("base.user_admin")
        # Healthy baseline: several stage-advances per week for weeks 1-6.
        for week in range(1, 7):
            for _ in range(4):
                self._touch(salesperson, week)
        # Current week (0): nothing — a clear drop vs. the baseline.
        detector = DealVelocityDropDetector(
            params={"min_weeks_for_baseline": 4, "z_threshold": 1.0})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertTrue(
            any(f.res_id == salesperson.id for f in findings),
            "expected the salesperson to be flagged for a velocity drop")

    def test_steady_velocity_not_flagged(self):
        salesperson = self.env.ref("base.user_admin")
        for week in range(0, 7):
            for _ in range(3):
                self._touch(salesperson, week)
        detector = DealVelocityDropDetector(
            params={"min_weeks_for_baseline": 4})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertFalse(any(f.res_id == salesperson.id for f in findings))

    def test_leads_with_no_user_excluded(self):
        self._touch(False, 0)
        detector = DealVelocityDropDetector(
            params={"min_weeks_for_baseline": 1})
        findings = list(detector.compute(self.env, self.scope_company))
        self.assertEqual(findings, [])
