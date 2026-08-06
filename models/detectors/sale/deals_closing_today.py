# detectors/sale/deals_closing_today.py
from dateutil.relativedelta import relativedelta
from odoo import fields
from ...constants import SEVERITY_WARNING
from ._common import (
    open_opportunity_domain,
)
from ..base import (
    PulseDetectorBase, PulseFinding,
)


class DealsClosingTodayDetector(PulseDetectorBase):
    TECHNICAL_NAME = "sale.deals_closing_today"
    DEFAULT_PARAMS = {
        "horizon_days": 0,   # 0 = today only; N = today through today+N
        "min_expected_revenue": 0.0,
    }

    def compute(self, env, scope):
        today = fields.Date.context_today(env.user)
        horizon = today + relativedelta(days=self.params["horizon_days"])

        domain = open_opportunity_domain(scope.company) + [
            ("stage_id.is_won", "=", False),
            ("date_deadline", ">=", today),
            ("date_deadline", "<=", horizon),
            ("expected_revenue", ">", self.params["min_expected_revenue"]),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(
            domain, order="date_deadline, expected_revenue desc")

        for lead in leads:
            deadline = fields.Date.to_date(lead.date_deadline)
            when = "today" if deadline == today else f"by {deadline}"
            yield PulseFinding(
                res_model="crm.lead",
                res_id=lead.id,
                res_name=lead.name,
                summary=f"{lead.name} closes {when} — "
                        f"{lead.expected_revenue:.0f} "
                        f"{lead.company_currency.symbol}",
                severity=SEVERITY_WARNING,
                metric_value=lead.expected_revenue,
            )
