# tests/test_pulse_run_wizard.py
"""Tests for wizards/pulse_run_wizard.py — the "Run For User..." manual
trigger. action_run is a thin delegate to pulse.config.action_admin_run_now
(no run-triggering logic of its own), so these tests focus on the wizard's
own responsibilities: computing which users are selectable, validating the
user_id-required-for-audience='user' case, and delegating correctly.
"""
from odoo.exceptions import UserError

from .common import PulseTransactionCase


class TestPulseRunWizard(PulseTransactionCase):

    def _make_wizard(self, **values):
        return self.env["pulse.run.wizard"].create({
            "config_id": self.config.id,
            **values,
        })

    def test_allowed_user_ids_reflects_config_user_group(self):
        wizard = self._make_wizard()
        self.assertEqual(
            set(wizard.allowed_user_ids.ids),
            set(self.config.user_group_id.all_user_ids.ids))
        self.assertIn(self.user_a, wizard.allowed_user_ids)

    def test_action_run_requires_user_id_when_audience_is_user(self):
        wizard = self._make_wizard(audience="user")
        with self.assertRaises(UserError):
            wizard.action_run()

    def test_action_run_company_audience_creates_company_run(self):
        wizard = self._make_wizard(audience="company")
        wizard.action_run()
        run = self.env["pulse.run"].search(
            [("config_id", "=", self.config.id)], order="id desc", limit=1)
        self.assertEqual(run.audience, "company")

    def test_action_run_user_audience_creates_run_scoped_to_that_user(self):
        wizard = self._make_wizard(audience="user", user_id=self.user_a.id)
        wizard.action_run()
        run = self.env["pulse.run"].search(
            [("config_id", "=", self.config.id)], order="id desc", limit=1)
        self.assertEqual(run.audience, "user")
        self.assertEqual(run.user_id, self.user_a)

    def test_action_run_does_not_server_side_validate_user_in_allowed_group(self):
        """Known, accepted gap (as of this iteration): user_id's restriction
        to config.user_group_id.all_user_ids is enforced only by the view's
        domain (client-side). Nothing in action_run re-checks it, so a user
        outside the group can still be targeted if the record is created/
        called directly (ORM, RPC) rather than through the wizard form. This
        test pins today's actual behavior so a future tightening is a
        deliberate, visible change to this test — not silent."""
        outsider = self._make_user(
            "Outsider", "pulse_outsider", self.env.ref("base.group_user"))
        self.assertNotIn(outsider, self.config.user_group_id.all_user_ids)

        wizard = self._make_wizard(audience="user", user_id=outsider.id)
        wizard.action_run()  # does not raise today

        run = self.env["pulse.run"].search(
            [("config_id", "=", self.config.id)], order="id desc", limit=1)
        self.assertEqual(run.user_id, outsider)
