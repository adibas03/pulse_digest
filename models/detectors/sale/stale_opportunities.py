# detectors/sale/stale_opportunities.py
from dateutil.relativedelta import relativedelta
from odoo import fields
from ...constants import (
    SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from ._common import (
    _DEFAULT_PARAMS,
    open_opportunity_domain,
)
from ..base import (
    PulseDetectorBase, PulseFinding,
)


class StaleOpportunitiesDetector(PulseDetectorBase):
    TECHNICAL_NAME = "sale.stale_opportunities"
    DEFAULT_PARAMS = _DEFAULT_PARAMS.get(TECHNICAL_NAME, {})

    def compute(self, env, scope):
        self.validate_severity_thresholds(self.params["severity_thresholds"])
        today = fields.Date.context_today(env.user)
        cutoff = today - relativedelta(days=self.params["stale_days"])

        domain = open_opportunity_domain(scope.company) + [
            ("stage_id.is_won", "=", False),
            ("date_last_stage_update", "<", cutoff),
            ("expected_revenue", ">", self.params["min_expected_revenue"]),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(domain)

        for lead in leads:
            last_move = fields.Date.to_date(lead.date_last_stage_update)
            days = (
                today - last_move).days if last_move else self.params["stale_days"]

            sev = SEVERITY_INFO
            if days >= self.params["severity_thresholds"][SEVERITY_CRITICAL]:
                sev = SEVERITY_CRITICAL
            elif days >= self.params["severity_thresholds"][SEVERITY_WARNING]:
                sev = SEVERITY_WARNING

            yield PulseFinding(
                res_model="crm.lead",
                res_id=lead.id,
                res_name=lead.name,
                summary=f"{lead.name} ({lead.stage_id.name}): no movement "
                        f"for {days}d — {lead.expected_revenue:.0f} "
                        f"{lead.company_currency.symbol}",
                severity=sev,
                metric_value=days,
            )
