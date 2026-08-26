"""Credit limit breach detector.

Flags customers whose current outstanding AR balance (`credit` field on
res.partner) exceeds their configured `credit_limit`. Unlike the other two
accounting detectors, this one queries res.partner rather than account.move
— credit limits are a partner-level concept — so it does NOT compose from
`customer_invoice_domain`. Documented as part of the §5.3b spec.

API status (verified Nov 2025 against odoo/odoo@19.0 source):
    - `credit` (computed: current outstanding AR balance on res.partner)
    - `credit_limit` (admin-configured threshold on res.partner)
    All three confirmed as the correct 19.0 field names. No further verification
    needed.

Suppression behaviour: SUPPRESSIBLE = True (a partner can sit over limit day
after day) with AGE_FIELD = None (no natural "since" date on the partner
record). The v1 suppression gate honours that combination by delivering every
run — see _suppression_gate in pulse_config.py. The v1.1 per-recipient
pulse.finding.state table closes this gap.
"""

from ...constants import (
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
)
from ..base import (
    PulseDetectorBase,
    PulseFinding,
)


class CreditLimitBreachDetector(PulseDetectorBase):
    """Flag customers whose outstanding AR balance exceeds their credit limit."""

    TECHNICAL_NAME = "account.credit_limit_breach"

    # Persisting condition: same partner can sit over limit day after day.
    # But there is no natural age field on res.partner for "when did the
    # breach start." AGE_FIELD = None signals to _suppression_gate that this
    # detector wants suppression but cannot provide its own age — so v1
    # delivers it every run. v1.1 per-recipient state closes this.
    SUPPRESSIBLE = True
    AGE_FIELD = None

    DEFAULT_PARAMS = {
        # Don't flag breaches below this absolute amount (in partner currency).
        # Useful to ignore rounding-noise breaches like 0.01 over limit.
        "min_breach_amount": 0.0,
        # Severity is driven by HOW FAR over limit, expressed as a fraction
        # of the limit itself. 0.10 = 10% over -> warning, 0.25 -> critical.
        "severity_thresholds": {
            # Fraction of credit_limit by which `credit` exceeds it.
            # 0.10 = 10% over -> warning; 0.25 = 25% over -> critical.
            SEVERITY_WARNING: 0.10,
            SEVERITY_CRITICAL: 0.25,
        },
    }

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])

        # `res.partner.credit` is company-dependent (same partner has
        # different outstanding-AR values per company). Without with_company,
        # both the search and the per-record reads below would use whatever
        # company env happened to be in — typically the cron user's main
        # company, not necessarily scope.company. Scope all reads explicitly.
        Partner = env["res.partner"].with_company(scope.company)

        # `credit > 0` is a quick filter to skip the (typically large) set of
        # partners with no current AR; the comparison against credit_limit
        # happens per record below.
        domain = [
            ("credit_limit", ">", 0),
            ("credit", ">", 0),
        ]

        # User-scope: narrow to partners where this user is the assigned
        # salesperson. Partners with NO assigned salesperson are deliberately
        # invisible to per-user digests in v1 — they appear only in the
        # company-wide digest, which is the safety net.
        if scope.is_user:
            domain.append(("user_id", "=", scope.user.id))

        # Multi-company filtering on res.partner is handled by record rules
        # together with with_company() above; no Python .filtered() for
        # company is needed.
        partners = Partner.search(domain)

        for partner in partners:
            breach_amount = partner.credit - partner.credit_limit
            if breach_amount <= self.params["min_breach_amount"]:
                continue

            breach_ratio = breach_amount / partner.credit_limit
            sev = SEVERITY_WARNING
            if breach_ratio >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL

            yield PulseFinding(
                res_model="res.partner",
                res_id=partner.id,
                res_name=partner.name,
                summary=f"{partner.name}: {partner.credit:.0f} "
                        f"vs limit {partner.credit_limit:.0f} "
                        f"({breach_ratio:+.0%})",
                severity=sev,
                metric_value=partner.credit,
                baseline_value=partner.credit_limit,
                deviation=breach_ratio,
            )
