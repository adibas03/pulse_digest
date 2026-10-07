# tests/test_security.py
"""Tests for the Pulse security model: two-tier groups (Viewer, implied by
every internal user; Administrator), the ACL split between them, and the
record rules scoping pulse.config/pulse.run to actual recipients.

There used to be a third tier, Recipient, between the two — removed (see
pulse_security.xml's header): nothing checked membership in it, since
config/run visibility was always decided by real recipient-list membership,
not Pulse tier. self.group_recipient (from the shared fixture) is now just
a plain membership bucket used to build a per-user audience group for
tests, not a Pulse group — see common.py.
"""
from odoo.exceptions import AccessError

from .common import PulseTransactionCase


class TestGroupHierarchy(PulseTransactionCase):

    def test_admin_implies_viewer(self):
        self.assertIn(self.group_viewer, self.group_admin.implied_ids)

    def test_every_internal_user_has_viewer(self):
        internal_group = self.env.ref("base.group_user")
        self.assertIn(self.group_viewer, internal_group.implied_ids)

    def test_admin_user_is_transitively_a_viewer(self):
        self.assertIn(self.user_admin, self.group_viewer.all_user_ids)


class TestViewerAccess(PulseTransactionCase):
    """A plain internal user — no explicit Pulse group — should get Viewer
    automatically via base.group_user."""

    def test_plain_internal_user_cannot_read_a_config_they_are_not_a_recipient_of(self):
        plain_user = self._make_user(
            "Plain Internal User", "pulse_plain_user",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            self.config.with_user(plain_user).read(["name"])

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


class TestRunLineAccess(PulseTransactionCase):
    """pulse.run.line is admin-only: only group_pulse_admin has an ACL row.
    Raw findings can name records a recipient has no right to read (e.g. a
    colleague's deal under CRM's "Own Documents Only"), so non-admins —
    Recipient tier included, even for their own runs — get no direct access
    and read findings only through pulse.run.digest_html (see
    test_digest_access_filtering.py). These tests pin that no non-admin
    path to a line exists, not just that a rule XML record does.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.run_line_access_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved — no compute() call
        })

    def _make_line(self, run):
        return self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test",
            "summary": "a finding",
        })

    def test_recipient_cannot_read_own_run_lines(self):
        run = self.config.run_digest("user", user=self.user_a)
        line = self._make_line(run)
        with self.assertRaises(AccessError):
            self.env["pulse.run.line"].with_user(self.user_a).search(
                [("id", "=", line.id)])

    def test_recipient_cannot_read_other_users_run_lines(self):
        run = self.config.run_digest("user", user=self.user_b)
        line = self._make_line(run)
        with self.assertRaises(AccessError):
            line.with_user(self.user_a).read(["summary"])

    def test_recipient_cannot_read_company_wide_run_lines(self):
        run = self.config.run_digest("company")
        line = self._make_line(run)
        with self.assertRaises(AccessError):
            line.with_user(self.user_a).read(["summary"])

    def test_recipient_of_the_run_still_cannot_read_its_lines(self):
        # Being the run's actual audience opens the run (see
        # TestRunVisibility), never its raw lines.
        run = self.config.run_digest("company")
        self.config.company_recipient_ids = [(4, self.user_a.id)]
        line = self._make_line(run)
        self.assertEqual(
            self.env["pulse.run"].with_user(self.user_a).search(
                [("id", "=", run.id)]), run)
        with self.assertRaises(AccessError):
            line.with_user(self.user_a).read(["summary"])

    def test_plain_internal_user_cannot_read_run_lines(self):
        run = self.config.run_digest("user", user=self.user_a)
        line = self._make_line(run)
        plain_user = self._make_user(
            "Plain Internal User 7", "pulse_plain_user_7",
            self.env.ref("base.group_user"))
        with self.assertRaises(AccessError):
            line.with_user(plain_user).read(["summary"])

    def test_admin_sees_all_run_lines(self):
        user_run = self.config.run_digest("user", user=self.user_a)
        company_run = self.config.run_digest("company")
        user_line = self._make_line(user_run)
        company_line = self._make_line(company_run)
        seen = self.env["pulse.run.line"].with_user(self.user_admin).search(
            [("id", "in", [user_line.id, company_line.id])])
        self.assertEqual(len(seen), 2)


class TestRunVisibility(PulseTransactionCase):
    """pulse_run_user_rule (attached at the Viewer tier): a run is visible
    to the people it is actually for — its own owner (per-user), listed
    company_recipient_ids (company-wide), and members of the config's
    recipient_group_ids (any run) — evaluated live against the config, and
    regardless of Pulse tier. Everything here uses a plain internal user
    (base.group_user only, so Viewer via implication and nothing more) to
    prove access follows the audience, not a Recipient-tier grant.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = cls._make_user(
            "Audience Viewer", "pulse_audience_viewer",
            cls.env.ref("base.group_user"))
        cls.audience = cls.env["res.groups"].create({"name": "Test Audience"})

    def _visible(self, user, run):
        return bool(self.env["pulse.run"].with_user(user).search(
            [("id", "=", run.id)]))

    def test_owner_without_recipient_tier_sees_own_per_user_run(self):
        run = self.config.run_digest("user", user=self.viewer)
        self.assertTrue(self._visible(self.viewer, run))

    def test_unrelated_internal_user_sees_no_run(self):
        company_run = self.config.run_digest("company")
        user_run = self.config.run_digest("user", user=self.user_a)
        self.assertFalse(self._visible(self.viewer, company_run))
        self.assertFalse(self._visible(self.viewer, user_run))

    def test_company_recipient_sees_company_run(self):
        run = self.config.run_digest("company")
        self.config.company_recipient_ids = [(4, self.viewer.id)]
        self.assertTrue(self._visible(self.viewer, run))

    def test_company_recipient_does_not_see_other_users_per_user_run(self):
        # company_recipient_ids receive the company-wide digest only; it
        # doesn't open anyone's individually-scoped run.
        self.config.company_recipient_ids = [(4, self.viewer.id)]
        run = self.config.run_digest("user", user=self.user_a)
        self.assertFalse(self._visible(self.viewer, run))

    def test_group_member_sees_company_and_forwarded_per_user_runs(self):
        self.config.recipient_group_ids = [(6, 0, [self.audience.id])]
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        company_run = self.config.run_digest("company")
        user_run = self.config.run_digest("user", user=self.user_a)
        self.assertTrue(self._visible(self.viewer, company_run))
        self.assertTrue(self._visible(self.viewer, user_run))

    def test_access_follows_group_membership_live(self):
        run = self.config.run_digest("company")
        self.config.recipient_group_ids = [(6, 0, [self.audience.id])]
        self.assertFalse(self._visible(self.viewer, run))

        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        self.assertTrue(self._visible(self.viewer, run))

        self.audience.user_ids = [(3, self.viewer.id)]
        self.env.flush_all()
        self.assertFalse(self._visible(self.viewer, run))

    def test_removed_company_recipient_loses_access(self):
        run = self.config.run_digest("company")
        self.config.company_recipient_ids = [(4, self.viewer.id)]
        self.assertTrue(self._visible(self.viewer, run))
        self.config.company_recipient_ids = [(3, self.viewer.id)]
        self.assertFalse(self._visible(self.viewer, run))

    def test_group_member_from_another_company_cannot_see_run(self):
        # The company boundary comes from the global company rule, not
        # from pulse_run_user_rule itself.
        other_company = self.env["res.company"].create({"name": "Other Co"})
        outsider = self.env["res.users"].create({
            "name": "Outsider",
            "login": "pulse_run_outsider",
            "email": "pulse_run_outsider@example.com",
            "company_id": other_company.id,
            "company_ids": [(6, 0, [other_company.id])],
            "group_ids": [(4, self.env.ref("base.group_user").id)],
        })
        self.config.recipient_group_ids = [(6, 0, [self.audience.id])]
        self.audience.user_ids = [(4, outsider.id)]
        self.env.flush_all()
        run = self.config.run_digest("company")
        self.assertFalse(self._visible(outsider, run))

    def test_visibility_is_read_only(self):
        # The rule applies to reads only, and the Viewer ACL row is
        # read-only — being a recipient never grants write/delete.
        run = self.config.run_digest("user", user=self.viewer)
        with self.assertRaises(AccessError):
            run.with_user(self.viewer).write({"status": "failed"})
        with self.assertRaises(AccessError):
            run.with_user(self.viewer).unlink()


class TestConfigVisibility(PulseTransactionCase):
    """pulse_config_user_rule (attached at the Viewer tier): a config is
    visible to the people it would deliver to — mirroring
    pulse.config.is_user_recipient per digest_mode — and to admins, and to
    nobody else. Uses a plain internal user (Viewer via base.group_user only).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer = cls._make_user(
            "Config Viewer", "pulse_config_viewer_only",
            cls.env.ref("base.group_user"))
        cls.audience = cls.env["res.groups"].create({"name": "Config Audience"})

    def _visible(self, user, config=None):
        config = config or self.config
        return bool(self.env["pulse.config"].with_user(user).search(
            [("id", "=", config.id)]))

    def test_unlisted_internal_user_sees_no_config(self):
        self.assertFalse(self._visible(self.viewer))

    def test_company_recipient_sees_config_in_company_mode(self):
        self.config.write({
            "digest_mode": "company",
            "company_recipient_ids": [(4, self.viewer.id)],
        })
        self.assertTrue(self._visible(self.viewer))

    def test_company_recipient_does_not_see_config_in_per_user_mode(self):
        self.config.write({
            "digest_mode": "per_user",
            "company_recipient_ids": [(4, self.viewer.id)],
        })
        self.assertFalse(self._visible(self.viewer))

    def test_user_group_member_sees_config_in_per_user_mode(self):
        self.config.write({
            "digest_mode": "per_user",
            "user_group_id": self.audience.id,
        })
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        self.assertTrue(self._visible(self.viewer))

    def test_user_group_member_does_not_see_config_in_company_mode(self):
        self.config.write({
            "digest_mode": "company",
            "user_group_id": self.audience.id,
        })
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        self.assertFalse(self._visible(self.viewer))

    def test_recipient_group_member_sees_config_in_every_mode(self):
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        for mode in ("company", "per_user", "both"):
            self.config.write({
                "digest_mode": mode,
                "recipient_group_ids": [(6, 0, [self.audience.id])],
            })
            self.assertTrue(self._visible(self.viewer), mode)

    def test_access_follows_group_membership_live(self):
        self.config.recipient_group_ids = [(6, 0, [self.audience.id])]
        self.assertFalse(self._visible(self.viewer))
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        self.assertTrue(self._visible(self.viewer))
        self.audience.user_ids = [(3, self.viewer.id)]
        self.env.flush_all()
        self.assertFalse(self._visible(self.viewer))

    def test_admin_sees_every_config(self):
        hidden = self.env["pulse.config"].create({
            "name": "Not Listing The Admin",
            "company_id": self.config.company_id.id,
            "digest_mode": "company",
            "company_recipient_ids": [(6, 0, [self.user_a.id])],
        })
        self.assertTrue(self._visible(self.user_admin, hidden))

    def test_teams_only_see_their_own_config(self):
        sales = self.env["pulse.config"].create({
            "name": "Sales Team Digest",
            "company_id": self.config.company_id.id,
            "digest_mode": "company",
            "recipient_group_ids": [(6, 0, [self.audience.id])],
        })
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        self.assertTrue(self._visible(self.viewer, sales))
        self.assertFalse(self._visible(self.viewer, self.config))

    def test_visibility_agrees_with_is_user_recipient(self):
        # The rule duplicates the compute's logic; keep them in step.
        self.audience.user_ids = [(4, self.viewer.id)]
        self.env.flush_all()
        scenarios = [
            {"digest_mode": "company", "company_recipient_ids": [(6, 0, [self.viewer.id])],
             "user_group_id": False, "recipient_group_ids": [(5, 0, 0)]},
            {"digest_mode": "per_user", "company_recipient_ids": [(6, 0, [self.viewer.id])],
             "user_group_id": False, "recipient_group_ids": [(5, 0, 0)]},
            {"digest_mode": "per_user", "company_recipient_ids": [(5, 0, 0)],
             "user_group_id": self.audience.id, "recipient_group_ids": [(5, 0, 0)]},
            {"digest_mode": "company", "company_recipient_ids": [(4, self.user_admin.id)],
             "user_group_id": self.audience.id, "recipient_group_ids": [(5, 0, 0)]},
            {"digest_mode": "both", "company_recipient_ids": [(4, self.user_admin.id)],
             "user_group_id": False, "recipient_group_ids": [(6, 0, [self.audience.id])]},
            {"digest_mode": "both", "company_recipient_ids": [(4, self.user_admin.id)],
             "user_group_id": False, "recipient_group_ids": [(5, 0, 0)]},
        ]
        for vals in scenarios:
            self.config.write({**vals, "company_recipient_ids": vals["company_recipient_ids"]})
            flag = self.config.with_user(self.viewer).sudo().is_user_recipient
            self.assertEqual(self._visible(self.viewer), flag, vals)

    def test_detector_lines_follow_their_config(self):
        detector = self.env["pulse.detector"].create({
            "name": "Visibility Fixture",
            "technical_name": "test.config_visibility_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved
        })
        line = self.env["pulse.config.detector"].create({
            "config_id": self.config.id,
            "detector_id": detector.id,
        })
        lines = self.env["pulse.config.detector"].with_user(self.viewer)
        self.assertFalse(lines.search([("id", "=", line.id)]))
        self.config.write({
            "digest_mode": "company",
            "company_recipient_ids": [(4, self.viewer.id)],
        })
        self.assertTrue(lines.search([("id", "=", line.id)]))

    def test_admin_sees_every_detector_line(self):
        detector = self.env["pulse.detector"].create({
            "name": "Visibility Fixture 2",
            "technical_name": "test.config_visibility_fixture_2",
            "category": "accounting",
            "detector_class": "x.y.Z",
        })
        line = self.env["pulse.config.detector"].create({
            "config_id": self.config.id,
            "detector_id": detector.id,
        })
        found = self.env["pulse.config.detector"].with_user(
            self.user_admin).search([("id", "=", line.id)])
        self.assertTrue(found)


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
