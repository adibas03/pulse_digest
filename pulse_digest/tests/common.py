# tests/common.py
"""Shared fixtures for Pulse tests.

Accounting-detector tests mix in AccountTestInvoicingCommon separately (see
test_detectors_accounting.py) since they need a chart of accounts; this base
covers what every other test needs: the three Pulse groups, a couple of
recipient users, an admin user, and a pulse.config to attach detector lines
to.
"""
from odoo.tests.common import TransactionCase


class PulseTransactionCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Keep fixture configs free of the seeded default detectors, so
        # tests link exactly the detectors they mean to.
        cls.env = cls.env(context=dict(
            cls.env.context, pulse_no_default_detectors=True))

        cls.group_viewer = cls.env.ref("pulse_digest.group_pulse_viewer")
        cls.group_admin = cls.env.ref("pulse_digest.group_pulse_admin")
        # A plain group used only as a membership bucket for the fixture's
        # per-user audience — not a Pulse permission tier (that's just
        # group_viewer/group_admin now; see pulse_security.xml's header).
        cls.group_recipient = cls.env["res.groups"].create(
            {"name": "Test Pulse Recipients"})

        cls.user_a = cls._make_user("Pulse User A", "pulse_user_a",
                                     cls.group_recipient)
        cls.user_b = cls._make_user("Pulse User B", "pulse_user_b",
                                     cls.group_recipient)
        cls.user_admin = cls._make_user("Pulse Admin", "pulse_admin_user",
                                         cls.group_admin)

        cls.config = cls.env["pulse.config"].create({
            "name": "Test Pulse Config",
            "company_id": cls.env.company.id,
            "digest_mode": "both",
            "user_group_id": cls.group_recipient.id,
            # digest_mode="both" includes company-wide dispatch, which
            # requires at least one company recipient (user or group) per
            # pulse.config._check_company_recipients_set — without this,
            # every test using this fixture fails at class setup, not just
            # dispatch-related ones.
            "company_recipient_ids": [(6, 0, [cls.user_admin.id])],
        })

    @classmethod
    def _make_user(cls, name, login, group):
        # base.group_user (Internal User) is always included alongside the
        # Pulse group being tested — in real deployments Pulse groups are
        # layered onto an existing internal user, never a substitute for
        # one. Without it, a test fixture can lack baseline access needed
        # by unrelated code (e.g. mail.thread.create() reading res.company
        # to compute reply-to info), producing confusing AccessErrors that
        # have nothing to do with what the test is actually checking.
        return cls.env["res.users"].create({
            "name": name,
            "login": login,
            "email": f"{login}@example.com",
            "group_ids": [
                (4, cls.env.ref("base.group_user").id),
                (4, group.id),
            ],
        })

    def _link_detector(self, technical_name, active=True, params=None):
        """Link a catalog detector to self.config. Returns the
        pulse.config.detector line."""
        detector = self.env["pulse.detector"].search(
            [("technical_name", "=", technical_name)], limit=1)
        self.assertTrue(
            detector, f"detector {technical_name!r} not found in catalog — "
            "is data/pulse_detector_data.xml loaded?")
        return self.env["pulse.config.detector"].create({
            "config_id": self.config.id,
            "detector_id": detector.id,
            "active": active,
            "params": params or {},
        })
