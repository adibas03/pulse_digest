# tests/test_multi_config.py
"""Tests for several pulse.config records in one company (e.g. one digest
per team): the UNIQUE(company_id, name) constraint, that the configs run and
dispatch independently, and that the config name reaches the delivered
digest (subject and header).
"""
from unittest.mock import patch

from odoo.tools import mute_logger

from .common import PulseTransactionCase


class TestMultiConfigPerCompany(PulseTransactionCase):

    def _make_config(self, name, **vals):
        return self.env["pulse.config"].create({
            "name": name,
            "company_id": self.config.company_id.id,
            "digest_mode": "company",
            "company_recipient_ids": [(6, 0, [self.user_admin.id])],
            **vals,
        })

    def test_company_can_have_several_configs_with_different_names(self):
        sales = self._make_config("Sales Digest")
        accounting = self._make_config("Accounting Digest")
        configs = self.env["pulse.config"].search(
            [("company_id", "=", self.config.company_id.id)])
        for config in (self.config, sales, accounting):
            self.assertIn(config, configs)

    @mute_logger("odoo.sql_db")
    def test_same_name_in_same_company_is_rejected(self):
        self._make_config("Sales Digest")
        with self.assertRaises(Exception), self.env.cr.savepoint():
            self._make_config("Sales Digest")

    def test_same_name_in_different_companies_is_allowed(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        self.env["pulse.config"].create({
            "name": self.config.name,
            "company_id": other_company.id,
            "digest_mode": "per_user",
        })  # must not raise

    def test_configs_run_independently(self):
        sales = self._make_config("Sales Digest")
        with patch.object(type(self.config), "_dispatch_run"):
            run = sales.run_digest("company", force=True)
        self.assertEqual(run.config_id, sales)
        self.assertFalse(self.config.run_ids)

    def test_recipients_are_per_config(self):
        plain = self._make_user(
            "Multi Config Plain", "pulse_multi_config_plain",
            self.env.ref("base.group_user"))
        sales = self._make_config(
            "Sales Digest",
            company_recipient_ids=[(6, 0, [plain.id])])
        self.assertTrue(sales.with_user(plain).is_user_recipient)
        self.assertFalse(self.config.with_user(plain).is_user_recipient)

    def test_subject_carries_the_config_name(self):
        sales = self._make_config("Sales Digest")
        run = self.env["pulse.run"].create({
            "config_id": sales.id,
            "audience": "company",
        })
        detector = self.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.multi_config_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved
        })
        self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test",
            "summary": "a finding",
        })
        sales.email_enabled = True
        sales._dispatch_run(run, self.user_admin)

        mail = self.env["mail.mail"].search(
            [("model", "=", "pulse.run"), ("res_id", "=", run.id)])
        self.assertTrue(mail)
        self.assertTrue(mail[0].subject.startswith("Sales Digest"))
        self.assertIn("Sales Digest", mail[0].body_html)
