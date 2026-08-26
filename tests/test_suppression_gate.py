# tests/test_suppression_gate.py
"""Tests for pulse.config._suppression_gate, calibrated to what's actually
built this iteration.

The full capped age-based backoff schedule (originally _suppression_phase_shows)
is shelved — see pulse_digest_spec.md §7/§14. The gate today is a deliberate
pass-through: every SUPPRESSIBLE/AGE_FIELD combination still delivers. These
tests exist to (a) prove that pass-through behavior is complete and correct
for the present iteration, and (b) act as a tripwire — if someone re-enables
SUPPRESSIBLE/AGE_FIELD on a real detector expecting suppression to kick in,
these tests document that it still won't, until the backoff schedule is
actually built.
"""
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)
from .common import PulseTransactionCase


class NotSuppressibleDetector(PulseDetectorBase):
    TECHNICAL_NAME = "test.not_suppressible"
    SUPPRESSIBLE = False
    AGE_FIELD = None


class SuppressibleNoAgeFieldDetector(PulseDetectorBase):
    """Mirrors credit_limit_breach's actual declared shape."""
    TECHNICAL_NAME = "test.suppressible_no_age"
    SUPPRESSIBLE = True
    AGE_FIELD = None


class SuppressibleWithAgeFieldDetector(PulseDetectorBase):
    """Mirrors what overdue_invoices/stale_opportunities WOULD declare once
    the backoff schedule ships — currently nothing in the codebase actually
    sets this combination, so this class exists purely to exercise the
    gate's third branch."""
    TECHNICAL_NAME = "test.suppressible_with_age"
    SUPPRESSIBLE = True
    AGE_FIELD = "create_date"


def _make_finding():
    return PulseFinding(
        res_model="res.partner", res_id=1, res_name="x", summary="s")


class TestSuppressionGatePassThrough(PulseTransactionCase):

    def test_not_suppressible_always_delivers(self):
        self.assertTrue(
            self.config._suppression_gate(
                NotSuppressibleDetector, _make_finding()))

    def test_suppressible_with_no_age_field_always_delivers(self):
        # This is credit_limit_breach's exact case: it opts into suppression
        # but has no natural "since" date on res.partner to anchor a backoff
        # schedule to, so the gate delivers every run regardless of version.
        self.assertTrue(
            self.config._suppression_gate(
                SuppressibleNoAgeFieldDetector, _make_finding()))

    def test_suppressible_with_age_field_still_delivers_this_iteration(self):
        # This is the branch that WOULD run the backoff schedule once it
        # ships. This iteration it's still a pass-through — this test fails
        # (correctly) the moment that schedule is implemented and this
        # assertion needs updating alongside it.
        self.assertTrue(
            self.config._suppression_gate(
                SuppressibleWithAgeFieldDetector, _make_finding()))

    def test_gate_never_raises_regardless_of_finding_shape(self):
        # The gate doesn't currently read finding.res_model/res_id at all
        # (no age lookup happens), so an obviously-bogus finding shouldn't
        # matter either.
        bogus = PulseFinding(
            res_model="does.not.exist", res_id=999999, res_name="?",
            summary="bogus")
        self.assertTrue(
            self.config._suppression_gate(
                SuppressibleWithAgeFieldDetector, bogus))


class TestSuppressionContractOnRealDetectors(PulseTransactionCase):
    """Regression guard on the actual shipped detectors' class attributes,
    so drift between the spec's roadmap and the real code is caught here
    rather than discovered again by hand."""

    def test_credit_limit_breach_declares_suppressible_no_age(self):
        from odoo.addons.pulse_digest.models.detectors.account.credit_limit_breach import (
            CreditLimitBreachDetector,
        )
        self.assertTrue(CreditLimitBreachDetector.SUPPRESSIBLE)
        self.assertIsNone(CreditLimitBreachDetector.AGE_FIELD)

    def test_overdue_invoices_does_not_yet_declare_suppression(self):
        # Shelved this iteration (pulse_digest_spec.md §5.2/§14) — this
        # detector inherits the base defaults rather than opting in, until
        # the backoff schedule is built.
        from odoo.addons.pulse_digest.models.detectors.account.overdue_invoices import (
            OverdueInvoicesDetector,
        )
        self.assertFalse(OverdueInvoicesDetector.SUPPRESSIBLE)
        self.assertIsNone(OverdueInvoicesDetector.AGE_FIELD)

    def test_stale_opportunities_does_not_yet_declare_suppression(self):
        from odoo.addons.pulse_digest.models.detectors.sale.stale_opportunities import (
            StaleOpportunitiesDetector,
        )
        self.assertFalse(StaleOpportunitiesDetector.SUPPRESSIBLE)
        self.assertIsNone(StaleOpportunitiesDetector.AGE_FIELD)

    def test_other_three_detectors_use_base_defaults(self):
        from odoo.addons.pulse_digest.models.detectors.account.payment_delay_outlier import (
            PaymentDelayOutlierDetector,
        )
        from odoo.addons.pulse_digest.models.detectors.sale.deals_closing_today import (
            DealsClosingTodayDetector,
        )
        from odoo.addons.pulse_digest.models.detectors.sale.deal_velocity_drop import (
            DealVelocityDropDetector,
        )
        for cls in (PaymentDelayOutlierDetector, DealsClosingTodayDetector,
                    DealVelocityDropDetector):
            self.assertFalse(cls.SUPPRESSIBLE, f"{cls.__name__} unexpected")
            self.assertIsNone(cls.AGE_FIELD, f"{cls.__name__} unexpected")

    def test_end_to_end_no_line_is_ever_suppressed_this_iteration(self):
        # Integration-level confirmation of the pass-through: linking the
        # real credit_limit_breach detector (SUPPRESSIBLE=True) to a config
        # and running it should never produce a suppressed (i.e. dropped)
        # finding — every finding compute() yields becomes a line.
        from unittest.mock import patch
        from odoo.addons.pulse_digest.models.detectors.base import Scope

        with patch(
            "odoo.addons.pulse_digest.models.detectors.account."
            "credit_limit_breach.CreditLimitBreachDetector.compute",
            return_value=iter([_make_finding()]),
        ):
            self._link_detector("account.credit_limit_breach")
            run = self.config.run_digest("company")
            self.assertEqual(len(run.line_ids), 1)
