# tests/test_default_detectors.py
"""Tests for default-detector seeding: a new pulse.config starts with one
active line per detector flagged is_default_enabled whose dependency modules
are installed (pulse.config._default_detector_lines).

The shared fixture switches seeding off (pulse_no_default_detectors) so other
tests link exactly what they mean to; these tests turn it back on. Fixture
detectors are created here rather than relying on the seeded catalog, which
depends on which apps (account, crm) the test DB has installed.
"""
from .common import PulseTransactionCase


class TestDefaultDetectorSeeding(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Detector = cls.env["pulse.detector"]

        def make(name, **vals):
            return Detector.create({
                "name": name,
                "technical_name": "test.default_seed_" + name.lower(),
                "category": "accounting",
                "detector_class": "x.y.Z",  # never resolved
                **vals,
            })

        cls.default_on = make("On", is_default_enabled=True)
        cls.default_off = make("Off", is_default_enabled=False)
        cls.default_unavailable = make(
            "Unavailable", is_default_enabled=True,
            dependency_modules="pulse_no_such_module")

    def _new_config(self, name, **vals):
        return self.env["pulse.config"].with_context(
            pulse_no_default_detectors=False).create({
                "name": name,
                "digest_mode": "per_user",
                **vals,
            })

    def test_new_config_gets_available_default_detectors(self):
        config = self._new_config("Seeded")
        detectors = config.detector_line_ids.detector_id
        self.assertIn(self.default_on, detectors)
        self.assertTrue(all(detectors.mapped("is_default_enabled")))
        self.assertTrue(all(detectors.mapped("is_available")))

    def test_non_default_detector_is_not_seeded(self):
        config = self._new_config("Seeded")
        self.assertNotIn(self.default_off, config.detector_line_ids.detector_id)

    def test_default_detector_with_missing_module_is_skipped(self):
        config = self._new_config("Seeded")
        self.assertNotIn(
            self.default_unavailable, config.detector_line_ids.detector_id)

    def test_seeded_lines_are_active_with_no_param_overrides(self):
        config = self._new_config("Seeded")
        line = config.detector_line_ids.filtered(
            lambda l: l.detector_id == self.default_on)
        self.assertTrue(line.active)
        self.assertFalse(line.params)

    def test_explicit_detector_lines_opt_out_of_seeding(self):
        config = self._new_config("Explicit", detector_line_ids=[(5, 0, 0)])
        self.assertFalse(config.detector_line_ids)

    def test_explicit_lines_replace_the_defaults(self):
        config = self._new_config("Explicit", detector_line_ids=[
            (0, 0, {"detector_id": self.default_off.id})])
        self.assertEqual(config.detector_line_ids.detector_id, self.default_off)

    def test_default_lines_returned_by_default_get(self):
        # What the unsaved form shows the admin, before saving.
        defaults = self.env["pulse.config"].with_context(
            pulse_no_default_detectors=False).default_get(
                ["detector_line_ids"])
        self.assertTrue(defaults["detector_line_ids"])

    def test_fixture_config_stays_empty(self):
        self.assertFalse(self.config.detector_line_ids)
