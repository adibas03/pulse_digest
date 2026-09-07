# tests/test_security.py
"""Tests for the Pulse security model: three-tier groups (Viewer, implied by
every internal user; Recipient; Administrator), the ACL split between them,
and the record rule scoping pulse.run to "own runs only" for recipients.
"""
from odoo.exceptions import AccessError

from .common import PulseTransactionCase


class TestGroupHierarchy(PulseTransactionCase):

    def test_admin_implies_recipient(self):
        self.assertIn(self.group_recipient, self.group_admin.implied_ids)

    def test_recipient_implies_viewer(self):
        self.assertIn(self.group_viewer, self.group_recipient.implied_ids)

    def test_every_internal_user_has_viewer(self):
        internal_group = self.env.ref("base.group_user")
        self.assertIn(self.group_viewer, internal_group.implied_ids)

    def test_admin_user_is_transitively_a_viewer_and_recipient(self):
        self.assertIn(self.user_admin, self.group_viewer.all_user_ids)
        self.assertIn(self.user_admin, self.group_recipient.all_user_ids)


class TestViewerAccess(PulseTransactionCase):
    """A plain internal user — no explicit Pulse group — should get Viewer
    automatically via base.group_user."""

    def test_plain_internal_user_can_read_pulse_config(self):
        plain_user = self._make_user(
            "Plain Internal User", "pulse_plain_user",
            self.env.ref("base.group_user"))
        self.config.with_user(plain_user).read(["name"])  # must not raise

    def test_plain_internal_user_can_read_detector_catalog(self):
        plain_user = self._make_user(
            "Plain Internal User 2", "pulse_plain_user_2",
            self.env.ref("base.group_user"))
        detectors = self.env["pulse.detector"].with_user(
            plain_user).search([])
        self.assertTrue(detectors)

    def test_plain_internal_user_cannot_write_pulse_config(self):
        plain_user = self._make_user(
            "Plain Internal User 3", "pulse_plain_user_3",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            self.config.with_user(plain_user).write({"name": "Hacked"})

    def test_plain_internal_user_cannot_read_pulse_run(self):
        run = self.config.run_digest("company")
        plain_user = self._make_user(
            "Plain Internal User 4", "pulse_plain_user_4",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            run.with_user(plain_user).read(["status"])

    def test_plain_internal_user_cannot_trigger_admin_run_now(self):
        plain_user = self._make_user(
            "Plain Internal User 5", "pulse_plain_user_5",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            self.config.with_user(plain_user).action_admin_run_now(
                audience="company")

    def test_plain_internal_user_cannot_access_run_wizard(self):
        plain_user = self._make_user(
            "Plain Internal User 6", "pulse_plain_user_6",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            self.env["pulse.run.wizard"].with_user(plain_user).create({
                "config_id": self.config.id,
            })


class TestRecipientAccess(PulseTransactionCase):

    def test_recipient_sees_own_per_user_run(self):
        run = self.config.run_digest("user", user=self.user_a)
        seen = self.env["pulse.run"].with_user(self.user_a).search(
            [("id", "=", run.id)])
        self.assertEqual(seen, run)

    def test_recipient_does_not_see_other_users_run(self):
        run = self.config.run_digest("user", user=self.user_b)
        seen = self.env["pulse.run"].with_user(self.user_a).search(
            [("id", "=", run.id)])
        self.assertFalse(seen)

    def test_recipient_does_not_see_company_wide_run(self):
        run = self.config.run_digest("company")
        seen = self.env["pulse.run"].with_user(self.user_a).search(
            [("id", "=", run.id)])
        self.assertFalse(seen)

    def test_recipient_cannot_create_pulse_run(self):
        with self.assertRaises(AccessError):
            self.env["pulse.run"].with_user(self.user_a).create({
                "config_id": self.config.id,
                "audience": "user",
                "user_id": self.user_a.id,
            })

    def test_recipient_can_read_pulse_config_via_viewer(self):
        self.config.with_user(self.user_a).read(["name"])  # must not raise

    def test_recipient_cannot_write_pulse_config(self):
        with self.assertRaises(AccessError):
            self.config.with_user(self.user_a).write({"name": "Hacked"})

    def test_recipient_cannot_trigger_admin_run_now(self):
        with self.assertRaises(AccessError):
            self.config.with_user(self.user_a).action_admin_run_now(
                audience="company")

    def test_recipient_cannot_access_run_wizard(self):
        with self.assertRaises(AccessError):
            self.env["pulse.run.wizard"].with_user(self.user_a).create({
                "config_id": self.config.id,
            })


class TestAdminAccess(PulseTransactionCase):

    def test_admin_sees_every_run(self):
        company_run = self.config.run_digest("company")
        user_run = self.config.run_digest("user", user=self.user_a)
        seen = self.env["pulse.run"].with_user(self.user_admin).search(
            [("id", "in", [company_run.id, user_run.id])])
        self.assertEqual(len(seen), 2)

    def test_admin_can_write_pulse_config(self):
        self.config.with_user(self.user_admin).write({"name": "Renamed"})
        self.assertEqual(self.config.name, "Renamed")

    def test_admin_can_create_and_unlink_detector_catalog_entries(self):
        detector = self.env["pulse.detector"].with_user(
            self.user_admin).create({
                "name": "Admin Made",
                "technical_name": "test.admin_made",
                "category": "accounting",
                "detector_class": "x.y.Z",
            })
        detector.with_user(self.user_admin).unlink()

    def test_admin_can_trigger_admin_run_now(self):
        self.config.with_user(self.user_admin).action_admin_run_now(
            audience="company")  # must not raise
        run = self.env["pulse.run"].search(
            [("config_id", "=", self.config.id)], order="id desc", limit=1)
        self.assertEqual(run.audience, "company")

    def test_admin_can_create_and_run_the_run_wizard(self):
        wizard = self.env["pulse.run.wizard"].with_user(
            self.user_admin).create({
                "config_id": self.config.id,
                "audience": "company",
            })
        wizard.action_run()  # must not raise
        run = self.env["pulse.run"].search(
            [("config_id", "=", self.config.id)], order="id desc", limit=1)
        self.assertEqual(run.audience, "company")
