# detectors/account/_common.py

from ...constants import (SEVERITY_WARNING, SEVERITY_CRITICAL)


"""Shared account.move query fragments for the accounting detectors.

Deduplicates the *query shape*, not the Odoo selection strings (those stay
inline — they are Odoo's vocabulary). Keeping the base domain in one place
prevents two detectors silently filtering different invoice sets.
"""

_DEFAULT_PARAMS = {
    "account.credit_limit_breach": {
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
    },
    "account.overdue_invoices": {
        "min_days_overdue": 1,
        "min_amount": 0.0,
        "severity_thresholds": {
            SEVERITY_WARNING: 30,    # >= 30 days overdue -> warning
            SEVERITY_CRITICAL: 60,   # >= 60 days overdue -> critical
        },
    },
    "account.payment_delay_outlier": {
        "lookback_weeks": 8,
        "min_payments_for_baseline": 4,
        "z_threshold": 1.5,
    }
}


def customer_invoice_domain(company):
    """Base domain: posted customer invoices for `company`.

    Deliberately does NOT constrain payment_state — callers add the
    payment_state filter they need (unpaid/partial vs paid), because that is
    exactly where the two detectors legitimately diverge.
    """
    return [
        ("move_type", "=", "out_invoice"),
        ("state", "=", "posted"),
        ("company_id", "=", company.id),
    ]
