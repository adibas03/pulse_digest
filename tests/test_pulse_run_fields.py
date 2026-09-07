# tests/test_pulse_run_fields.py
"""Tests for pulse.run's severity-stat computed fields
(_compute_severity_stats: critical_count/warning_count/info_count/
worst_severity) and pulse.run.line's severity_sequence (the worst-first sort
key the findings list view orders by).

Lines are created directly against a manually-created pulse.run rather than
via run_digest/a real detector — these fields are pure aggregation over
whatever line_ids exist, so there's no need to exercise the detector
framework to test them. detector_id is a throwaway test-only catalog entry
(same reasoning as test_run_execution.py's fakes) rather than a real seeded
detector — it's just a required FK slot here, never resolved/compute()'d,
and pointing it at real catalog data would needlessly couple these tests to
that data's continued existence under its current technical_name.
"""
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from .common import PulseTransactionCase


class TestPulseRunSeverityStats(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.pulse_run_fields_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved — see module docstring
        })

    def _make_run(self):
        return self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })

    def _make_line(self, run, severity):
        return self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test",
            "severity": severity,
            "summary": f"a {severity} finding",
        })

    def test_severity_stats_no_lines(self):
        run = self._make_run()
        self.assertEqual(run.critical_count, 0)
        self.assertEqual(run.warning_count, 0)
        self.assertEqual(run.info_count, 0)
        self.assertFalse(run.worst_severity)

    def test_severity_stats_all_three_present(self):
        run = self._make_run()
        self._make_line(run, SEVERITY_CRITICAL)
        self._make_line(run, SEVERITY_WARNING)
        self._make_line(run, SEVERITY_INFO)
        self.assertEqual(run.critical_count, 1)
        self.assertEqual(run.warning_count, 1)
        self.assertEqual(run.info_count, 1)
        self.assertEqual(run.worst_severity, SEVERITY_CRITICAL)

    def test_severity_stats_only_warning_and_info(self):
        run = self._make_run()
        self._make_line(run, SEVERITY_WARNING)
        self._make_line(run, SEVERITY_INFO)
        self.assertEqual(run.critical_count, 0)
        self.assertEqual(run.worst_severity, SEVERITY_WARNING)

    def test_severity_stats_only_info(self):
        run = self._make_run()
        self._make_line(run, SEVERITY_INFO)
        self.assertEqual(run.worst_severity, SEVERITY_INFO)

    def test_severity_stats_counts_multiple_of_same_severity(self):
        run = self._make_run()
        self._make_line(run, SEVERITY_CRITICAL)
        self._make_line(run, SEVERITY_CRITICAL)
        self._make_line(run, SEVERITY_WARNING)
        self.assertEqual(run.critical_count, 2)
        self.assertEqual(run.warning_count, 1)
        self.assertEqual(run.worst_severity, SEVERITY_CRITICAL)


class TestPulseRunLineSeveritySequence(PulseTransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.detector = cls.env["pulse.detector"].create({
            "name": "Test Fixture Detector",
            "technical_name": "test.pulse_run_line_sequence_fixture",
            "category": "accounting",
            "detector_class": "x.y.Z",  # never resolved — see module docstring
        })

    def _make_run_and_line(self, severity):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        line = self.env["pulse.run.line"].create({
            "run_id": run.id,
            "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test",
            "severity": severity,
            "summary": f"a {severity} finding",
        })
        return run, line

    def test_severity_sequence_worst_first_values(self):
        _, critical_line = self._make_run_and_line(SEVERITY_CRITICAL)
        _, warning_line = self._make_run_and_line(SEVERITY_WARNING)
        _, info_line = self._make_run_and_line(SEVERITY_INFO)
        self.assertEqual(critical_line.severity_sequence, 0)
        self.assertEqual(warning_line.severity_sequence, 1)
        self.assertEqual(info_line.severity_sequence, 2)

    def test_findings_sort_worst_first_by_severity_sequence(self):
        run = self.env["pulse.run"].create({
            "config_id": self.config.id,
            "audience": "company",
        })
        info = self.env["pulse.run.line"].create({
            "run_id": run.id, "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test", "severity": SEVERITY_INFO,
            "summary": "info finding",
        })
        critical = self.env["pulse.run.line"].create({
            "run_id": run.id, "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test", "severity": SEVERITY_CRITICAL,
            "summary": "critical finding",
        })
        warning = self.env["pulse.run.line"].create({
            "run_id": run.id, "detector_id": self.detector.id,
            "res_model": "res.partner",
            "res_id": self.env.company.partner_id.id,
            "res_name": "Test", "severity": SEVERITY_WARNING,
            "summary": "warning finding",
        })
        ordered = self.env["pulse.run.line"].search(
            [("run_id", "=", run.id)], order="severity_sequence")
        self.assertEqual(list(ordered.ids), [critical.id, warning.id, info.id])
