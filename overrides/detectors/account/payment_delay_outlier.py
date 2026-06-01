# detectors/account/payment_delay_outlier.py
import statistics
from dateutil.relativedelta import relativedelta
from odoo import fields
from odoo.addons.pulse_digest.models.constants import (
    SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from odoo.addons.pulse_digest.models.detectors.account._common import (
    customer_invoice_domain,
)
from odoo.addons.pulse_digest.models.detectors.base import (
    PulseDetectorBase, PulseFinding,
)


class PaymentDelayOutlierDetector(PulseDetectorBase):
    """Flag customers whose latest payment delay is unusually high vs. their
    own 8-week rolling mean."""

    TECHNICAL_NAME = "account.payment_delay_outlier"
    DEFAULT_PARAMS = {
        "lookback_weeks": 8,
        "min_payments_for_baseline": 4,
        "z_threshold": 1.5,
    }

    def compute(self, env, scope):
        # Find customers with paid invoices in the last week
        lookback_days = self.params["lookback_weeks"] * 7
        cutoff = fields.Date.today() - relativedelta(days=lookback_days)

        domain = customer_invoice_domain(scope.company) + [
            ("payment_state", "=", "paid"),
            ("invoice_date", ">=", cutoff),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(
                env, domain, "account.move", scope.user)

        invoices = env["account.move"].search(domain)

        # Group by customer, compute days-to-pay for each
        by_partner = {}
        for inv in invoices:
            paid_date = self._first_payment_date(inv)
            if not paid_date or not inv.invoice_date_due:
                continue
            days_to_pay = (paid_date - inv.invoice_date_due).days
            by_partner.setdefault(inv.partner_id, []).append(
                (inv.invoice_date, days_to_pay, inv)
            )

        for partner, entries in by_partner.items():
            if len(entries) < self.params["min_payments_for_baseline"]:
                continue
            entries.sort(key=lambda e: e[0])
            *historical, latest = entries
            historical_delays = [d for _, d, _ in historical]
            mean = statistics.mean(historical_delays)
            stdev = statistics.stdev(historical_delays) if len(
                historical_delays) > 1 else 0
            if stdev == 0:
                continue
            latest_delay = latest[1]
            z = (latest_delay - mean) / stdev
            if z >= self.params["z_threshold"]:
                yield PulseFinding(
                    res_model="res.partner",
                    res_id=partner.id,
                    res_name=partner.name,
                    summary=f"{partner.name} paid {latest_delay}d late "
                            f"(baseline {mean:.1f}d, +{z:.1f}σ)",
                    severity=SEVERITY_WARNING if z < 2.5 else SEVERITY_CRITICAL,
                    metric_value=latest_delay,
                    baseline_value=mean,
                    deviation=z,
                )

    def _first_payment_date(self, invoice):
        # Walk reconciled payments to find first payment date
        payments = invoice._get_reconciled_payments()
        if not payments:
            return None
        return min(p.date for p in payments)
