# detectors/sale/deal_velocity_drop.py
import statistics
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from odoo import fields
from ...constants import (
    SEVERITY_WARNING, SEVERITY_CRITICAL,
)
from ._common import (
    open_opportunity_domain,
)
from ..base import (
    PulseDetectorBase, PulseFinding,
)


class DealVelocityDropDetector(PulseDetectorBase):
    """Flag salespeople whose stage-advance count this week is unusually low
    vs their own rolling weekly baseline.

    NOTE: counts stage *updates* in each week as a proxy for velocity. A more
    precise version would read mail.tracking / a stage-history model; that is a
    v2 refinement. Documented so the simplification is explicit, not hidden.
    """

    TECHNICAL_NAME = "sale.deal_velocity_drop"
    DEFAULT_PARAMS = {
        "lookback_weeks": 8,
        "min_weeks_for_baseline": 4,
        "z_threshold": 1.5,
    }

    def compute(self, env, scope):
        weeks = self.params["lookback_weeks"]
        today = fields.Date.context_today(env.user)
        start = today - relativedelta(weeks=weeks)

        # This detector is inherently per-salesperson, so it only makes sense
        # to evaluate velocity grouped by user. In company scope we evaluate
        # every salesperson; in user scope, just that user.
        domain = open_opportunity_domain(scope.company) + [
            ("date_last_stage_update", ">=", start),
            ("user_id", "!=", False),
        ]
        if scope.is_user:
            domain = self.apply_user_scope(env, domain, "crm.lead", scope.user)

        leads = env["crm.lead"].search(domain)

        # Bucket stage-advances per (user, week-index)
        by_user = defaultdict(lambda: defaultdict(int))
        for lead in leads:
            d = fields.Date.to_date(lead.date_last_stage_update)
            if not d:
                continue
            week_index = (today - d).days // 7   # 0 = current week
            if 0 <= week_index < weeks:
                by_user[lead.user_id][week_index] += 1

        for user, week_counts in by_user.items():
            current = week_counts.get(0, 0)
            historical = [week_counts.get(w, 0) for w in range(1, weeks)]
            if len(historical) < self.params["min_weeks_for_baseline"]:
                continue
            mean = statistics.mean(historical)
            stdev = statistics.stdev(historical) if len(historical) > 1 else 0
            if stdev == 0:
                continue
            # Velocity DROP: current is unusually LOW, so z is negative.
            z = (current - mean) / stdev
            if z <= -self.params["z_threshold"]:
                yield PulseFinding(
                    res_model="res.users",
                    res_id=user.id,
                    res_name=user.name,
                    summary=f"{user.name}: {current} stage advances this week "
                            f"(baseline {mean:.1f}, {z:.1f}σ)",
                    severity=SEVERITY_WARNING if z > -2.5 else SEVERITY_CRITICAL,
                    metric_value=current,
                    baseline_value=mean,
                    deviation=z,
                )
