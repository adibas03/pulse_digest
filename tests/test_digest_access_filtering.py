# tests/test_digest_access_filtering.py
"""Unit-level tests for pulse.run's render-time access re-check
(pulse_digest_spec.md §8.3): _filter_lines_readable_by (which findings a
specific recipient can actually read, batched by res_model) and
_render_digest_body's hidden-count disclosure.

_filter_lines_readable_by is exercised against pulse.run itself as the
referenced res_model — reusing the already-tested pulse.run record rule
(test_security.py) as a known-restricted target, rather than depending on
assumptions about some other app's (e.g. CRM's) default ACL/group setup,
which may not even be installed/configured the same way in a bare test
database.

Dispatch-level integration (does a restricted recipient still get
dispatched to, with the right content) lives in test_channel_dispatch.py;
this file only covers the two methods in isolation.
"""
from .common import PulseTransactionCase


class TestFilterLinesReadableBy(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.digest_access_filtering_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved
        })

    def _make_line(self, run, res_model, res_id):
        return self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": res_model,
            "res_id": res_id,
            "res_name": "Test",
            "summary": "a finding",
        })

    def _make_digest_run(self):
        return self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })

    def test_recipient_sees_line_referencing_a_run_they_can_read(self):
        own_run = self.config.run_digest("user", user=self.user_a)
        digest_run = self._make_digest_run()
        line = self._make_line(digest_run, "pulse.run", own_run.id)

        visible = digest_run._filter_lines_readable_by(self.user_a)
        self.assertEqual(visible, line)

    def test_recipient_does_not_see_line_referencing_a_run_they_cannot_read(self):
        other_run = self.config.run_digest("user", user=self.user_b)
        digest_run = self._make_digest_run()
        self._make_line(digest_run, "pulse.run", other_run.id)

        visible = digest_run._filter_lines_readable_by(self.user_a)
        self.assertFalse(visible)

    def test_admin_sees_every_line_regardless_of_referenced_run_owner(self):
        other_run = self.config.run_digest("user", user=self.user_b)
        digest_run = self._make_digest_run()
        line = self._make_line(digest_run, "pulse.run", other_run.id)

        visible = digest_run._filter_lines_readable_by(self.user_admin)
        self.assertEqual(visible, line)

    def test_stale_res_model_is_excluded_not_crashed(self):
        digest_run = self._make_digest_run()
        self._make_line(digest_run, "pulse.nonexistent.model", 999999)

        visible = digest_run._filter_lines_readable_by(self.user_a)
        self.assertFalse(visible)

    def test_filtering_does_not_drop_sibling_lines_on_readable_models(self):
        # Two lines, two different res_models, both readable — confirms
        # the per-model batching correctly reunites all visible lines
        # across models, not just the first one processed.
        own_run = self.config.run_digest("user", user=self.user_a)
        digest_run = self._make_digest_run()
        line1 = self._make_line(digest_run, "pulse.run", own_run.id)
        line2 = self._make_line(
            digest_run, "res.partner", self.env.company.partner_id.id)

        visible = digest_run._filter_lines_readable_by(self.user_a)
        self.assertEqual(set(visible.ids), {line1.id, line2.id})


class TestRenderDigestBodyDisclosure(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.render_digest_body_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",
        })

    def _make_run_with_lines(self, count):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        lines = self.env["pulse.run.line"]
        for i in range(count):
            lines |= self.env["pulse.run.line"].create({
                "run_id": run.id,
                "detector_id": self.detector.id,
                "res_model": "res.partner",
                "res_id": self.env.company.partner_id.id,
                "res_name": "Test",
                "summary": f"finding {i}",
            })
        return run, lines

    def test_no_hidden_notice_when_all_lines_visible(self):
        run, lines = self._make_run_with_lines(2)
        body = str(run._render_digest_body(lines))
        self.assertNotIn("not shown", body)
        self.assertIn("finding 0", body)
        self.assertIn("finding 1", body)

    def test_hidden_notice_appended_when_some_lines_filtered(self):
        run, lines = self._make_run_with_lines(3)
        visible = lines[:2]
        body = str(run._render_digest_body(visible))
        self.assertIn("1 additional finding(s) not shown", body)
        self.assertIn("finding 0", body)

    def test_all_hidden_shows_dedicated_message_with_count(self):
        run, lines = self._make_run_with_lines(2)
        body = str(run._render_digest_body(self.env["pulse.run.line"]))
        self.assertIn("No findings visible to you", body)
        self.assertIn("2 not shown", body)

    def test_truly_empty_run_shows_generic_message(self):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        body = str(run._render_digest_body(self.env["pulse.run.line"]))
        self.assertIn("No findings for this run", body)
        self.assertNotIn("not shown", body)

    def test_lines_argument_is_required(self):
        run, _lines = self._make_run_with_lines(1)
        with self.assertRaises(TypeError):
            run._render_digest_body()
