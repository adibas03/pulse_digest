# tests/test_run_execution.py
"""Tests for the runner: run_digest, run_all_audiences, per-hour dedup,
_cron_is_due / _cron_run_digests, and exception isolation.

Uses two tiny test-only detectors (AlwaysFindsOneDetector, RaisesDetector)
registered as real pulse.detector catalog rows, rather than depending on the
production detectors' data fixtures — keeps these tests focused purely on
the runner, independent of accounting/CRM setup.
"""
from unittest.mock import patch

from odoo import fields

from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)
from .common import PulseTransactionCase


class AlwaysFindsOneDetector(PulseDetectorBase):
    TECHNICAL_NAME = "test.always_finds_one"

    def compute(self, env, scope):
        yield PulseFinding(
            res_model="res.partner", res_id=env.company.partner_id.id,
            res_name="Test", summary="always found",
        )


class RaisesDetector(PulseDetectorBase):
    TECHNICAL_NAME = "test.raises"

    def compute(self, env, scope):
        raise RuntimeError("boom")
        yield  # pragma: no cover — makes this a generator function


class TestRunExecution(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.working_detector = cls.env["pulse.detector"].create({
            "name": "Always Finds One",
            "technical_name": "test.always_finds_one",
            "category": "accounting",
            "detector_class":
                "odoo.addons.pulse_digest.tests.test_run_execution."
                "AlwaysFindsOneDetector",
        })
        cls.broken_detector = cls.env["pulse.detector"].create({
            "name": "Raises",
            "technical_name": "test.raises",
            "category": "accounting",
            "detector_class":
                "odoo.addons.pulse_digest.tests.test_run_execution."
                "RaisesDetector",
        })

    def test_run_digest_creates_run_and_lines(self):
        self._link_detector("test.always_finds_one")
        run = self.config.run_digest("company")
        self.assertEqual(run.status, "done")
        self.assertEqual(run.audience, "company")
        self.assertEqual(len(run.line_ids), 1)
        self.assertEqual(run.line_ids.summary, "always found")

    def test_run_digest_ignores_inactive_detector_lines(self):
        self._link_detector("test.always_finds_one", active=False)
        run = self.config.run_digest("company")
        self.assertEqual(len(run.line_ids), 0)

    def test_run_digest_dedup_returns_existing_run_within_the_hour(self):
        self._link_detector("test.always_finds_one")
        first = self.config.run_digest("company")
        second = self.config.run_digest("company")
        self.assertEqual(first.id, second.id)

    def test_run_digest_force_bypasses_dedup(self):
        self._link_detector("test.always_finds_one")
        first = self.config.run_digest("company")
        second = self.config.run_digest("company", force=True)
        self.assertNotEqual(first.id, second.id)

    def test_dedup_is_scoped_per_user(self):
        self._link_detector("test.always_finds_one")
        run_a = self.config.run_digest("user", user=self.user_a)
        run_b = self.config.run_digest("user", user=self.user_b)
        self.assertNotEqual(run_a.id, run_b.id)
        run_a_again = self.config.run_digest("user", user=self.user_a)
        self.assertEqual(run_a.id, run_a_again.id)

    def test_run_all_audiences_company_only(self):
        self.config.digest_mode = "company"
        self._link_detector("test.always_finds_one")
        self.config.run_all_audiences()
        self.assertEqual(len(self.config.run_ids), 1)
        self.assertEqual(self.config.run_ids.audience, "company")

    def test_run_all_audiences_per_user_only(self):
        self.config.digest_mode = "per_user"
        self._link_detector("test.always_finds_one")
        self.config.run_all_audiences()
        audiences = self.config.run_ids.mapped("audience")
        self.assertTrue(all(a == "user" for a in audiences))
        self.assertGreaterEqual(len(self.config.run_ids), 1)

    def test_run_all_audiences_both(self):
        self.config.digest_mode = "both"
        self._link_detector("test.always_finds_one")
        self.config.run_all_audiences()
        audiences = self.config.run_ids.mapped("audience")
        self.assertIn("company", audiences)
        self.assertIn("user", audiences)

    def test_run_all_audiences_includes_admin_via_group_membership(self):
        # user_group_id defaults to group_pulse_recipient; group_pulse_admin
        # implies it. Whether that's via all_user_ids' computed inclusion or
        # Odoo's own implied-group membership propagation, the observable
        # contract is the same: an admin ends up covered by a per-user run
        # without needing separate explicit Recipient membership.
        self.config.digest_mode = "per_user"
        self._link_detector("test.always_finds_one")
        self.config.run_all_audiences()
        run_users = self.config.run_ids.mapped("user_id")
        self.assertIn(self.user_admin, run_users)

    def test_failing_detector_marks_run_failed(self):
        self._link_detector("test.raises")
        with self.assertRaises(RuntimeError):
            self.config.run_digest("company")
        run = self.config.run_ids.sorted("started_at", reverse=True)[:1]
        self.assertEqual(run.status, "failed")
        self.assertIn("boom", run.error_message)

    def test_cron_run_digests_isolates_failure_per_config(self):
        other_config = self.env["pulse.config"].create({
            "name": "Other Config",
            "company_id": self.env.company.id,
            "digest_mode": "company",
            "run_time": self.config.run_time,
            "timezone": self.config.timezone,
        })
        self._link_detector("test.raises")
        self.env["pulse.config.detector"].create({
            "config_id": other_config.id,
            "detector_id": self.working_detector.id,
        })

        with patch.object(
                type(self.config), "_cron_is_due", return_value=True):
            # Should not raise even though self.config's detector will —
            # _cron_run_digests must isolate per-config failures.
            self.env["pulse.config"]._cron_run_digests()

        failed = self.config.run_ids.sorted("started_at", reverse=True)[:1]
        succeeded = other_config.run_ids.sorted(
            "started_at", reverse=True)[:1]
        self.assertEqual(failed.status, "failed")
        self.assertEqual(succeeded.status, "done")

    def test_cron_is_due_respects_run_time_hour(self):
        self.config.write({"run_time": 7.0, "timezone": "UTC"})
        due_time = fields.Datetime.from_string("2024-01-01 07:15:00")
        not_due_time = fields.Datetime.from_string("2024-01-01 08:15:00")
        self.assertTrue(self.config._cron_is_due(due_time))
        self.assertFalse(self.config._cron_is_due(not_due_time))

    def test_cron_is_due_false_if_already_ran_this_hour(self):
        self.config.write({
            "run_time": 7.0,
            "timezone": "UTC",
            "last_run_date": fields.Datetime.from_string("2024-01-01 07:05:00"),
        })
        due_time = fields.Datetime.from_string("2024-01-01 07:15:00")
        self.assertFalse(self.config._cron_is_due(due_time))

    def test_cron_is_due_true_if_last_run_was_a_different_hour(self):
        self.config.write({
            "run_time": 7.0,
            "timezone": "UTC",
            "last_run_date": fields.Datetime.from_string("2024-01-01 06:55:00"),
        })
        due_time = fields.Datetime.from_string("2024-01-01 07:15:00")
        self.assertTrue(self.config._cron_is_due(due_time))
