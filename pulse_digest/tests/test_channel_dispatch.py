# tests/test_channel_dispatch.py
"""Tests for pulse.config._dispatch_run: the config-level x user-level
channel gate, the email_sent/inapp_sent/whatsapp_sent flags, per-
channel/per-recipient failure isolation, and the render-time access
re-check (pulse_digest_spec.md §8.3) at the dispatch integration level —
does a recipient with restricted access to a finding's underlying record
still get dispatched to, with the content correctly hidden. The access
re-check's own unit-level behavior (_filter_lines_readable_by,
_render_digest_body's hidden-count disclosure) is covered separately in
test_digest_access_filtering.py; this file only checks the dispatch-loop
integration around it.

Calls _dispatch_run directly against a manually-built pulse.run + one line,
rather than going through run_digest — dispatch doesn't care how the line
got there, and this keeps these tests independent of the detector
framework/production detectors.

Real EmailChannel/InAppChannel are exercised for real (not mocked) for the
gating-matrix tests, verified via the actual mail.mail queue and
run.message_ids — this also catches a regression in their Odoo API calls,
not just our gating logic. WhatsApp needs no such setup: the whatsapp
module isn't a dependency of this one, so is_available() is False in the
test DB and it's a no-op by construction.

_dispatch_run already catches and logs per-channel exceptions internally
(see pulse_config.py) — it never re-raises for a channel/recipient failure,
so the failure-isolation tests below call it directly with no
try/except needed (unlike the detector-exception tests in
test_run_execution.py, where the exception genuinely propagates to the
caller).
"""
from unittest.mock import patch

from odoo.addons.pulse_digest.models.pulse_channel import CHANNELS, PulseChannel

from .common import PulseTransactionCase


class FakeChannel(PulseChannel):
    """Records every send() call; optionally fails for specific recipients."""

    TECHNICAL_NAME = "email"

    def __init__(self, fail_for_recipients=()):
        self.fail_for = set(fail_for_recipients)
        self.calls = []

    def is_available(self, env):
        return True

    def send(self, env, recipient, run, body_html, subject):
        self.calls.append(recipient.id)
        if recipient.id in self.fail_for:
            raise RuntimeError("boom")


class TestChannelDispatch(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Throwaway test-only catalog entry, not a real seeded detector —
        # it's just a required FK slot for pulse.run.line.detector_id here
        # (never resolved/compute()'d), and pointing it at real catalog
        # data would needlessly couple these dispatch tests to that data's
        # continued existence under its current technical_name.
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.channel_dispatch_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved
        })

    def _make_run_with_finding(self):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test",
            "summary": "a finding",
        })
        return run

    def _queued_mail_count(self, run):
        return self.env["mail.mail"].search_count(
            [("model", "=", "pulse.run"), ("res_id", "=", run.id)])

    def _make_run_with_restricted_finding(self, owner):
        """A run whose only finding references *owner*'s own per-user run
        — readable by owner (or an admin), not by anyone else. Reuses the
        already-tested pulse.run record rule (test_security.py) as a
        known-restricted target, rather than depending on some other
        app's (e.g. CRM's) default ACL/group setup, which may not even be
        configured the same way in a bare test database."""
        owner_run = self.config.run_digest("user", user=owner)
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": "pulse.run",
            "res_id": owner_run.id,
            "res_name": "Test",
            "summary": "a restricted finding",
        })
        return run

    def test_dispatch_sends_via_enabled_channels_and_sets_sent_flags(self):
        run = self._make_run_with_finding()
        self.config._dispatch_run(run, self.user_a)

        self.assertTrue(run.email_sent)
        self.assertTrue(run.inapp_sent)

        mail = self.env["mail.mail"].search(
            [("model", "=", "pulse.run"), ("res_id", "=", run.id)])
        self.assertTrue(mail)
        self.assertIn(self.user_a.email, mail.mapped("email_to"))

        posted = run.message_ids.filtered(
            lambda m: self.user_a.partner_id in m.partner_ids)
        self.assertTrue(posted)

    def test_dispatch_skips_channel_disabled_at_config_level(self):
        self.config.email_enabled = False
        run = self._make_run_with_finding()
        self.config._dispatch_run(run, self.user_a)

        self.assertFalse(run.email_sent)
        self.assertTrue(run.inapp_sent)
        self.assertEqual(self._queued_mail_count(run), 0)

    def test_dispatch_skips_channel_disabled_at_user_level(self):
        self.user_a.pulse_email_enabled = False
        run = self._make_run_with_finding()
        self.config._dispatch_run(run, self.user_a)

        self.assertFalse(run.email_sent)
        self.assertTrue(run.inapp_sent)
        self.assertEqual(self._queued_mail_count(run), 0)

    def test_dispatch_skips_empty_run(self):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        self.config._dispatch_run(run, self.user_a)

        self.assertFalse(run.email_sent)
        self.assertFalse(run.inapp_sent)
        self.assertEqual(self._queued_mail_count(run), 0)

    def test_whatsapp_unavailable_in_test_env_is_skipped(self):
        self.config.whatsapp_enabled = True
        self.user_a.pulse_whatsapp_enabled = True
        self.user_a.pulse_phone = "+15550000000"
        run = self._make_run_with_finding()
        self.config._dispatch_run(run, self.user_a)

        self.assertFalse(run.whatsapp_sent)

    def test_dispatch_isolates_channel_failure_from_other_channels(self):
        fake = FakeChannel(fail_for_recipients=[self.user_a.id])
        run = self._make_run_with_finding()

        with patch.dict(CHANNELS, {"email": fake}):
            self.config._dispatch_run(run, self.user_a)

        self.assertFalse(run.email_sent)
        self.assertTrue(run.inapp_sent)

    def test_dispatch_continues_to_next_recipient_after_a_failure(self):
        fake = FakeChannel(fail_for_recipients=[self.user_a.id])
        run = self._make_run_with_finding()

        with patch.dict(CHANNELS, {"email": fake}):
            self.config._dispatch_run(run, self.user_a | self.user_b)

        # Both recipients were attempted despite user_a's failing...
        self.assertEqual(set(fake.calls), {self.user_a.id, self.user_b.id})
        # ...and the run-level flag still reflects the recipient who
        # succeeded (email_sent means "sent to at least one recipient").
        self.assertTrue(run.email_sent)

    def test_dispatch_still_reaches_recipient_with_nothing_visible(self):
        # The old "skip this recipient entirely if nothing's visible"
        # behavior is gone — every recipient of a non-empty run gets
        # dispatched to, even if everything they'd see gets filtered out
        # by the access re-check; the message itself discloses that
        # rather than the recipient silently receiving nothing.
        run = self._make_run_with_restricted_finding(owner=self.user_b)
        self.config._dispatch_run(run, self.user_a)

        self.assertTrue(run.email_sent)
        self.assertTrue(run.inapp_sent)

        mail = self.env["mail.mail"].search(
            [("model", "=", "pulse.run"), ("res_id", "=", run.id)])
        self.assertTrue(mail)
        self.assertIn(self.user_a.email, mail.mapped("email_to"))

    def test_dispatch_message_discloses_but_does_not_leak_restricted_finding(self):
        run = self._make_run_with_restricted_finding(owner=self.user_b)
        self.config._dispatch_run(run, self.user_a)

        posted = run.message_ids.filtered(
            lambda m: self.user_a.partner_id in m.partner_ids)
        self.assertTrue(posted)
        self.assertIn("not shown", posted.body)
        self.assertNotIn("a restricted finding", posted.body)
