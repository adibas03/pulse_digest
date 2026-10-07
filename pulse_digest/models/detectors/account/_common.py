# detectors/account/_common.py

"""Shared account.move query fragments for the accounting detectors.

Deduplicates the *query shape*, not the Odoo selection strings (those stay
inline — they are Odoo's vocabulary). Keeping the base domain in one place
prevents two detectors silently filtering different invoice sets.
"""


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
