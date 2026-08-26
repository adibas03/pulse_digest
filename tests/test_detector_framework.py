# tests/test_detector_framework.py
"""Tests for the detector framework itself: PulseDetectorBase's contract,
Scope's construction rules and immutability, PulseFinding's severity
validation, and pulse.detector's is_available / _get_detector_class.

DummyDetector below is deliberately importable at
odoo.addons.pulse_digest.tests.test_detector_framework.DummyDetector so
_get_detector_class tests can resolve a real, controlled dotted path instead
of depending on one of the six production detectors' exact location.
"""
from odoo.tests.common import TransactionCase

from odoo.addons.pulse_digest.models.constants import (
    SEVERITIES, SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, Scope, PulseFinding,
)


class DummyDetector(PulseDetectorBase):
    TECHNICAL_NAME = "test.dummy"
    DEFAULT_PARAMS = {"threshold": 10}

    def compute(self, env, scope):
        yield PulseFinding(
            res_model="res.partner", res_id=1, res_name="Test",
            summary="dummy finding",
        )


class NamelessDetector(PulseDetectorBase):
    """No TECHNICAL_NAME set — used to test the base class's own guard."""
    pass


class TestPulseDetectorBaseContract(TransactionCase):

    def test_technical_name_required(self):
        with self.assertRaises(ValueError):
            NamelessDetector()

    def test_params_merge_overrides_defaults(self):
        d = DummyDetector(params={"threshold": 99, "extra": 1})
        self.assertEqual(d.params["threshold"], 99)
        self.assertEqual(d.params["extra"], 1)

    def test_params_fall_back_to_defaults_when_none(self):
        d = DummyDetector()
        self.assertEqual(d.params, {"threshold": 10})

    def test_suppressible_and_age_field_default(self):
        # Base defaults added specifically so a detector that never declares
        # these doesn't AttributeError the moment a suppression gate reads
        # them — see models/detectors/base.py.
        d = DummyDetector()
        self.assertFalse(d.SUPPRESSIBLE)
        self.assertIsNone(d.AGE_FIELD)

    def test_compute_is_a_generator(self):
        d = DummyDetector()
        findings = list(d.compute(self.env, Scope.company(self.env.company)))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].summary, "dummy finding")

    def test_validate_severity_thresholds_accepts_known_keys(self):
        thresholds = {SEVERITY_WARNING: 10, SEVERITY_CRITICAL: 20}
        result = DummyDetector.validate_severity_thresholds(thresholds)
        self.assertEqual(result, thresholds)

    def test_validate_severity_thresholds_rejects_unknown_key(self):
        with self.assertRaises(ValueError):
            DummyDetector.validate_severity_thresholds({"warn": 10})

    def test_apply_user_scope_prefers_user_id(self):
        d = DummyDetector()
        domain = d.apply_user_scope(
            self.env, [("x", "=", 1)], "crm.lead", self.env.ref("base.user_admin"))
        self.assertIn(("user_id", "=", self.env.ref("base.user_admin").id), domain)

    def test_apply_user_scope_falls_back_to_invoice_user_id(self):
        d = DummyDetector()
        domain = d.apply_user_scope(
            self.env, [("x", "=", 1)], "account.move",
            self.env.ref("base.user_admin"))
        self.assertIn(
            ("invoice_user_id", "=", self.env.ref("base.user_admin").id), domain)

    def test_apply_user_scope_no_match_returns_domain_unchanged(self):
        d = DummyDetector()
        base_domain = [("x", "=", 1)]
        domain = d.apply_user_scope(
            self.env, base_domain, "res.company", self.env.ref("base.user_admin"))
        self.assertEqual(domain, base_domain)


class TestScope(TransactionCase):

    def test_company_scope_requires_company(self):
        with self.assertRaises(ValueError):
            Scope.company(False)

    def test_user_scope_requires_user(self):
        with self.assertRaises(ValueError):
            Scope.user(False)

    def test_company_scope_shape(self):
        company = self.env.company
        scope = Scope.company(company)
        self.assertFalse(scope.is_user)
        self.assertEqual(scope.company, company)
        self.assertIsNone(scope.user)

    def test_user_scope_derives_company_from_user(self):
        user = self.env.ref("base.user_admin")
        scope = Scope.user(user)
        self.assertTrue(scope.is_user)
        self.assertEqual(scope.company, user.company_id)
        self.assertEqual(scope.user, user)

    def test_scope_is_immutable(self):
        scope = Scope.company(self.env.company)
        with self.assertRaises(AttributeError):
            scope.company = self.env.company

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            Scope("bogus", company=self.env.company)

    def test_user_kind_without_user_rejected(self):
        with self.assertRaises(ValueError):
            Scope(Scope.USER, company=self.env.company, user=None)

    def test_company_kind_with_user_rejected(self):
        with self.assertRaises(ValueError):
            Scope(Scope.COMPANY, company=self.env.company,
                  user=self.env.ref("base.user_admin"))

    def test_missing_company_rejected(self):
        with self.assertRaises(ValueError):
            Scope(Scope.COMPANY, company=None)


class TestPulseFinding(TransactionCase):

    def test_default_severity_is_info(self):
        f = PulseFinding(res_model="res.partner", res_id=1, res_name="x",
                          summary="s")
        self.assertEqual(f.severity, SEVERITY_INFO)

    def test_rejects_unknown_severity(self):
        with self.assertRaises(AssertionError):
            PulseFinding(res_model="res.partner", res_id=1, res_name="x",
                         summary="s", severity="warn")

    def test_accepts_every_known_severity(self):
        for sev in SEVERITIES:
            f = PulseFinding(res_model="res.partner", res_id=1, res_name="x",
                             summary="s", severity=sev)
            self.assertEqual(f.severity, sev)

    def test_optional_fields_default_none(self):
        f = PulseFinding(res_model="res.partner", res_id=1, res_name="x",
                          summary="s")
        self.assertIsNone(f.detail)
        self.assertIsNone(f.metric_value)
        self.assertIsNone(f.baseline_value)
        self.assertIsNone(f.deviation)


class TestPulseDetectorCatalog(TransactionCase):
    """pulse.detector's is_available compute and _get_detector_class resolver."""

    def _make_catalog_entry(self, technical_name, detector_class=None,
                             dependency_modules=None):
        return self.env["pulse.detector"].create({
            "name": technical_name,
            "technical_name": technical_name,
            "category": "accounting",
            "detector_class": detector_class or (
                "odoo.addons.pulse_digest.tests.test_detector_framework."
                "DummyDetector"),
            "dependency_modules": dependency_modules,
        })

    def test_is_available_true_with_no_dependencies(self):
        detector = self._make_catalog_entry("test.no_deps")
        self.assertTrue(detector.is_available)

    def test_is_available_true_when_dependency_installed(self):
        detector = self._make_catalog_entry(
            "test.has_dep", dependency_modules="base")
        self.assertTrue(detector.is_available)

    def test_is_available_false_when_dependency_missing(self):
        detector = self._make_catalog_entry(
            "test.missing_dep",
            dependency_modules="definitely_not_a_real_module_xyz")
        self.assertFalse(detector.is_available)

    def test_is_available_false_if_any_of_several_deps_missing(self):
        detector = self._make_catalog_entry(
            "test.partial_dep", dependency_modules="base,not_a_real_module_xyz")
        self.assertFalse(detector.is_available)

    def test_get_detector_class_resolves_real_dotted_path(self):
        detector = self.env["pulse.detector"].search(
            [("technical_name", "=", "account.overdue_invoices")], limit=1)
        self.assertTrue(detector, "seed data not loaded")
        cls = detector._get_detector_class()
        self.assertEqual(cls.TECHNICAL_NAME, "account.overdue_invoices")

    def test_get_detector_class_strips_surrounding_whitespace(self):
        # Regression: data/pulse_detector_data.xml wraps detector_class
        # across lines, which used to leak a leading "\n    " into the
        # stored string and break importlib.import_module.
        detector = self._make_catalog_entry(
            "test.whitespace",
            detector_class="\n    odoo.addons.pulse_digest.tests."
                            "test_detector_framework.DummyDetector    \n")
        cls = detector._get_detector_class()
        self.assertEqual(cls.TECHNICAL_NAME, "test.dummy")

    def test_technical_name_uniqueness_enforced(self):
        self._make_catalog_entry("test.dup")
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._make_catalog_entry("test.dup")

    def test_seed_catalog_has_six_detectors(self):
        detectors = self.env["pulse.detector"].search([])
        self.assertEqual(len(detectors), 6)
