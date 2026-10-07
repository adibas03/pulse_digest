# tests/test_recipient_resolution.py
"""Tests for who ends up as `recipients` in pulse.config.run_digest —
the company_recipient_ids / recipient_group_ids union, the multi-company
membership filter, and the "at least one company recipient" constraint.

Distinct from test_channel_dispatch.py, which tests _dispatch_run directly
with a manually-passed-in recipient and never exercises this resolution
step. Verified by patching _dispatch_run and capturing what recipients it
was actually invoked with, rather than exercising real channel sends — no
detector/finding setup needed, since the mock doesn't care whether
run.line_ids ends up empty.

recipient_group_ids is tested against a plain, dedicated group (team_group)
kept outside the Pulse group hierarchy (group_recipient/group_admin) so
membership here is exactly what each test sets, not affected by implied_ids
chains or the shared fixture's own group memberships.
"""
from unittest.mock import patch

from odoo.exceptions import ValidationError

from .common import PulseTransactionCase


class TestRecipientResolution(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team_group = cls.env["res.groups"].create({"name": "Test Team"})

    def _run_digest_recipients(self, audience, user=None):
        """Call run_digest and return the recordset _dispatch_run was
        actually invoked with, without exercising real dispatch."""
        with patch.object(type(self.config), "_dispatch_run") as mock_dispatch:
            self.config.run_digest(audience, user=user, force=True)
        self.assertTrue(mock_dispatch.called)
        _run_arg, recipients_arg = mock_dispatch.call_args.args
        return recipients_arg

    def test_company_wide_recipients_include_group_members(self):
        self.config.company_recipient_ids = [(5, 0, 0)]
        self.config.recipient_group_ids = [(6, 0, [self.team_group.id])]
        self.team_group.user_ids = [(6, 0, [self.user_a.id, self.user_b.id])]

        recipients = self._run_digest_recipients("company")
        self.assertEqual(set(recipients.ids), {self.user_a.id, self.user_b.id})

    def test_company_wide_recipients_union_individual_and_group(self):
        self.config.company_recipient_ids = [(6, 0, [self.user_admin.id])]
        self.config.recipient_group_ids = [(6, 0, [self.team_group.id])]
        self.team_group.user_ids = [(6, 0, [self.user_a.id])]

        recipients = self._run_digest_recipients("company")
        self.assertEqual(
            set(recipients.ids), {self.user_admin.id, self.user_a.id})

    def test_per_user_run_forwarded_to_group(self):
        # The core "decouple run from recipient" case: user_b's own
        # per-user run should still reach user_b AND be forwarded to
        # user_a via the group, even though the run's records are scoped
        # entirely to user_b.
        self.config.recipient_group_ids = [(6, 0, [self.team_group.id])]
        self.team_group.user_ids = [(6, 0, [self.user_a.id])]

        recipients = self._run_digest_recipients("user", user=self.user_b)
        self.assertEqual(
            set(recipients.ids), {self.user_b.id, self.user_a.id})

    def test_recipient_group_members_filtered_to_run_company(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        other_company_user = self.env["res.users"].create({
            "name": "Other Co User",
            "login": "pulse_other_co_user",
            "email": "pulse_other_co_user@example.com",
            "company_id": other_company.id,
            "company_ids": [(6, 0, [other_company.id])],
        })
        self.config.recipient_group_ids = [(6, 0, [self.team_group.id])]
        self.team_group.user_ids = [
            (6, 0, [self.user_a.id, other_company_user.id])]

        recipients = self._run_digest_recipients("company")
        self.assertIn(self.user_a.id, recipients.ids)
        self.assertNotIn(other_company_user.id, recipients.ids)

    def test_recipient_group_with_only_foreign_members_satisfies_constraint_but_dispatches_to_nobody(self):
        # A group can satisfy the save-time "at least one recipient"
        # constraint (the field is populated) while still resolving to
        # zero actual recipients at dispatch time, if none of its current
        # members belong to the run's company. Not a bug — the constraint
        # checks configuration, not live membership, which can change
        # after the config is saved — but worth pinning explicitly so the
        # two checks (save-time vs. dispatch-time) aren't conflated.
        other_company = self.env["res.company"].create({"name": "Other Co"})
        other_company_user = self.env["res.users"].create({
            "name": "Other Co User 2",
            "login": "pulse_other_co_user_2",
            "email": "pulse_other_co_user_2@example.com",
            "company_id": other_company.id,
            "company_ids": [(6, 0, [other_company.id])],
        })
        self.team_group.user_ids = [(6, 0, [other_company_user.id])]

        self.config.write({
            "digest_mode": "both",
            "company_recipient_ids": [(5, 0, 0)],
            "recipient_group_ids": [(6, 0, [self.team_group.id])],
        })  # must not raise — the field is populated

        recipients = self._run_digest_recipients("company")
        self.assertFalse(recipients)

    def test_recipient_group_ids_resolves_dynamically(self):
        self.config.recipient_group_ids = [(6, 0, [self.team_group.id])]
        self.team_group.user_ids = [(6, 0, [self.user_a.id])]

        # Add user_b to the group after it was already linked to the
        # config — should still be picked up, no config edit needed.
        self.team_group.user_ids = [(4, self.user_b.id)]

        recipients = self._run_digest_recipients("company")
        self.assertIn(self.user_b.id, recipients.ids)

    def test_constraint_satisfied_by_group_alone(self):
        self.team_group.user_ids = [(6, 0, [self.user_a.id])]
        # Must not raise: recipient_group_ids alone satisfies the
        # constraint even with company_recipient_ids empty.
        self.config.write({
            "digest_mode": "both",
            "company_recipient_ids": [(5, 0, 0)],
            "recipient_group_ids": [(6, 0, [self.team_group.id])],
        })

    def test_constraint_raises_when_both_empty_for_company_mode(self):
        with self.assertRaises(ValidationError):
            self.config.write({
                "digest_mode": "company",
                "company_recipient_ids": [(5, 0, 0)],
                "recipient_group_ids": [(5, 0, 0)],
            })

    def test_constraint_not_enforced_for_per_user_only_mode(self):
        self.config.write({
            "digest_mode": "per_user",
            "company_recipient_ids": [(5, 0, 0)],
            "recipient_group_ids": [(5, 0, 0)],
        })  # must not raise

    def test_empty_recipient_group_ids_does_not_break_dispatch(self):
        self.config.recipient_group_ids = [(5, 0, 0)]
        self.config.company_recipient_ids = [(6, 0, [self.user_admin.id])]

        recipients = self._run_digest_recipients("company")
        self.assertEqual(set(recipients.ids), {self.user_admin.id})


class TestIsUserRecipient(PulseTransactionCase):
    """pulse.config.is_user_recipient — the History button's gate: is the
    *viewing* user an actual recipient of this config, mirroring dispatch's
    resolution per digest_mode (plus admins). Non-stored and computed per
    uid, so each test reads it as the user in question.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.team_group = cls.env["res.groups"].create({"name": "Test Team"})
        cls.plain = cls._make_user(
            "Plain Recipient Check", "pulse_is_recipient_plain",
            cls.env.ref("base.group_user"))

    def _flag(self, user):
        # sudo() keeps the uid (the compute is per viewing user) but skips
        # the config record rule, which hides configs from non-recipients
        # — the flag is what's under test here, not row visibility (see
        # TestConfigVisibility in test_security.py).
        return self.config.with_user(user).sudo().is_user_recipient

    def test_admin_is_always_a_recipient(self):
        self.config.company_recipient_ids = [(6, 0, [self.user_a.id])]
        self.assertTrue(self._flag(self.user_admin))

    def test_unlisted_internal_user_is_not_a_recipient(self):
        self.config.company_recipient_ids = [(6, 0, [self.user_a.id])]
        self.assertFalse(self._flag(self.plain))

    def test_company_recipient_counts_in_company_mode(self):
        self.config.write({
            "digest_mode": "company",
            "company_recipient_ids": [(6, 0, [self.plain.id])],
        })
        self.assertTrue(self._flag(self.plain))

    def test_company_recipient_does_not_count_in_per_user_mode(self):
        self.config.write({
            "digest_mode": "per_user",
            "company_recipient_ids": [(6, 0, [self.plain.id])],
        })
        self.assertFalse(self._flag(self.plain))

    def test_user_group_member_counts_in_per_user_mode(self):
        self.config.write({"digest_mode": "per_user"})
        self.assertTrue(self._flag(self.user_a))
        self.assertFalse(self._flag(self.plain))

    def test_user_group_member_does_not_count_in_company_mode(self):
        self.config.write({
            "digest_mode": "company",
            "company_recipient_ids": [(6, 0, [self.plain.id])],
        })
        self.assertFalse(self._flag(self.user_a))

    def test_recipient_group_member_counts_in_every_mode(self):
        self.team_group.user_ids = [(6, 0, [self.plain.id])]
        self.env.flush_all()
        for mode in ("company", "per_user", "both"):
            self.config.write({
                "digest_mode": mode,
                "company_recipient_ids": [(5, 0, 0)],
                "recipient_group_ids": [(6, 0, [self.team_group.id])],
            })
            self.assertTrue(self._flag(self.plain), mode)

    def test_recipient_group_member_from_another_company_does_not_count(self):
        other_company = self.env["res.company"].create({"name": "Other Co"})
        outsider = self.env["res.users"].create({
            "name": "Outsider",
            "login": "pulse_is_recipient_outsider",
            "email": "pulse_is_recipient_outsider@example.com",
            "company_id": other_company.id,
            "company_ids": [(6, 0, [other_company.id])],
            "group_ids": [(4, self.env.ref("base.group_user").id)],
        })
        self.team_group.user_ids = [(6, 0, [self.plain.id, outsider.id])]
        self.env.flush_all()
        self.config.write({
            "recipient_group_ids": [(6, 0, [self.team_group.id])],
        })
        self.assertTrue(self._flag(self.plain))
        # The outsider can't open this config at all, so evaluate as them
        # via sudo (uid preserved) — the compute must still say no,
        # matching dispatch's company filter.
        self.assertFalse(
            self.config.with_user(outsider).sudo().is_user_recipient)

    def test_result_follows_the_viewing_user_on_the_same_record(self):
        self.config.write({
            "digest_mode": "company",
            "company_recipient_ids": [(6, 0, [self.plain.id])],
        })
        self.assertTrue(self._flag(self.plain))
        self.assertFalse(self._flag(self.user_a))
        # Read the first user again after the second — the per-uid cache
        # must not have been overwritten.
        self.assertTrue(self._flag(self.plain))
