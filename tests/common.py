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

        cls.group_viewer = cls.env.ref("pulse_digest.group_pulse_viewer")
        cls.group_recipient = cls.env.ref("pulse_digest.group_pulse_recipient")
        cls.group_admin = cls.env.ref("pulse_digest.group_pulse_admin")

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
        })

    @classmethod
    def _make_user(cls, name, login, group):
        return cls.env["res.users"].create({
            "name": name,
            "login": login,
            "email": f"{login}@example.com",
            "group_ids": [(4, group.id)],
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
