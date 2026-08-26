# detectors/account/overdue_invoices.py
from odoo import fields
from ...constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from ._common import (
    _DEFAULT_PARAMS,
    customer_invoice_domain,
)
from ..base import (
    PulseDetectorBase, PulseFinding,
)


class OverdueInvoicesDetector(PulseDetectorBase):
    TECHNICAL_NAME = "account.overdue_invoices"
    DEFAULT_PARAMS = _DEFAULT_PARAMS.get(TECHNICAL_NAME, {})

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])
        today = fields.Date.context_today(env.user)
        domain = customer_invoice_domain(scope.company) + [
            ("payment_state", "in", ("not_paid", "partial")),
            ("invoice_date_due", "<", today),
            ("amount_residual", ">", self.params["min_amount"]),
        ]

        if scope.is_user:
            domain = self.apply_user_scope(
                env, domain, "account.move", scope.user)

        invoices = env["account.move"].search(domain)

        for inv in invoices:
            days = (today - inv.invoice_date_due).days
            if days < self.params["min_days_overdue"]:
                continue

            sev = SEVERITY_INFO
            if days >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL
            elif days >= self.params["severity_thresholds"][SEVERITY_WARNING]:
                sev = SEVERITY_WARNING

            yield PulseFinding(
                res_model="account.move",
                res_id=inv.id,
                res_name=inv.name,
                summary=f"{inv.partner_id.name}: {inv.amount_residual} "
                        f"{inv.currency_id.symbol} overdue {days}d",
                severity=sev,
                metric_value=days,
            )
