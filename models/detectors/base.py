# models/detectors/base.py
from abc import abstractmethod

# NOTE: Detectors are plain Python classes, NOT models.Model subclasses, so
# they do not get `fields`, `relativedelta`, etc. for free. Every detector
# module that needs them imports explicitly:
#     from odoo import fields
#     from dateutil.relativedelta import relativedelta
# Severity values are plain strings ("info" | "warning" | "critical"); the
# canonical names live in constants.py. base.py imports only SEVERITIES, which
# it uses below to validate PulseFinding. Detectors, models, and tests import
# the severity constants from constants.py directly — there is one canonical
# import path, not via base. (If base ever becomes a deliberate facade for the
# detector API, re-exporting the severity names here would be the place to do
# it — but it is not one today.)
from ..constants import SEVERITIES, SEVERITY_INFO


class PulseDetectorBase:
    """Abstract base for all Pulse detectors.

    Subclasses MUST set:
        TECHNICAL_NAME: matches the technical_name on the pulse.detector record
        DEFAULT_PARAMS: dict of default params (overridable per config)

    Subclasses MUST implement:
        compute(env, scope): yields PulseFinding instances

    Detectors are STATELESS: they receive `env` as an argument on every call
    rather than storing it. This keeps a single detector instance safe to reuse
    across companies/users within one run.

    Scope is either:
        Scope.company(company)   — return findings for whole company
        Scope.user(user)         — return findings filtered to records this
                                   user owns/is responsible for
    """

    TECHNICAL_NAME = None
    DEFAULT_PARAMS = {}

    def __init__(self, params=None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        if self.TECHNICAL_NAME is None:
            raise ValueError('Detector subclass TECHNICAL NAME must be set')

    @abstractmethod
    def compute(self, env, scope):
        """Yield PulseFinding instances."""
        raise NotImplementedError

    # Helper for subclasses: applies user-scope domain to a base domain.
    # Override in subclass if the user-scope filter is non-standard.
    # `env` is passed in (not stored) to keep the detector stateless.
    def apply_user_scope(self, env, domain, model_name, user):
        """Default: filter by user_id field if it exists on the model."""
        model = env[model_name]
        if "user_id" in model._fields:
            return domain + [("user_id", "=", user.id)]
        if "invoice_user_id" in model._fields:
            return domain + [("invoice_user_id", "=", user.id)]
        return domain

    # Helper for subclasses whose params include a severity->threshold mapping.
    # Guards against a config override supplying an invalid severity key
    # (e.g. {"warn": 30}). Uses SEVERITIES (the canonical tuple) for the
    # membership check — this is the tuple's job, distinct from the individual
    # SEVERITY_* names used as the actual keys.
    @staticmethod
    def validate_severity_thresholds(thresholds):
        bad = [k for k in thresholds if k not in SEVERITIES]
        if bad:
            raise ValueError(
                f"Invalid severity key(s) in thresholds: {bad}. "
                f"Valid values: {SEVERITIES}")
        return thresholds


class Scope:
    """Detector execution scope. Construct via Scope.user() or Scope.company();
    both guarantee a coherent kind/user/company combination.

    `kind` values are owned by this class (Scope.USER / Scope.COMPANY) rather
    than living in constants.py — they are a control-flow discriminant intrinsic
    to Scope, never persisted, never rendered in a view, never leaving the
    detector layer. (If a scope kind ever becomes a stored/selectable field,
    move the selection list to constants.py at that point — not before.)
    """

    USER = "user"
    COMPANY = "company"

    # __slots__ = ("kind", "company", "user")

    def __init__(self, kind, company=None, user=None):
        if kind not in (self.USER, self.COMPANY):
            raise ValueError(f"Invalid scope kind: {kind!r}")
        if kind == self.USER and user is None:
            raise ValueError("user-scope requires a user")
        if kind == self.COMPANY and user is not None:
            raise ValueError("company-scope must not carry a user")
        if company is None:
            raise ValueError("scope requires a company")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "company", company)
        object.__setattr__(self, "user", user)

    def __setattr__(self, *_):
        raise AttributeError("Scope is immutable")

    @classmethod
    def company(cls, company):
        if not company:
            raise ValueError("Scope.company requires a company record")
        return cls(cls.COMPANY, company)

    @classmethod
    def user(cls, user):
        if not user:
            raise ValueError("Scope.user requires a user record")
        return cls(cls.USER, user.company_id, user=user)

    @property
    def is_user(self):
        return self.kind == self.USER


class PulseFinding:
    """One finding returned by a detector. Maps 1:1 to a pulse.run.line."""

    def __init__(self, res_model, res_id, res_name, summary,
                 severity=SEVERITY_INFO, detail=None,
                 metric_value=None, baseline_value=None, deviation=None):
        assert severity in SEVERITIES, f"Unknown severity: {severity!r}"
        self.res_model = res_model
        self.res_id = res_id
        self.res_name = res_name
        self.summary = summary
        self.severity = severity
        self.detail = detail
        self.metric_value = metric_value
        self.baseline_value = baseline_value
        self.deviation = deviation
