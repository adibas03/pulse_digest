import pytz
from odoo import api, models, fields
from . import pulse_run
from . import pulse_detector
from . import pulse_config_detector
from . import pulse_channel
from .detectors.base import Scope


def _tz_get(self):
    return [(x, x) for x in pytz.all_timezones]


class PulseConfig(models.Model):
    _name = "pulse.config"
    _description = "Pulse Configuration"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, default="Pulse Digest")
    company_id = fields.Many2one("res.company", required=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True, tracking=True)

    # Schedule
    run_time = fields.Float(default=7.0,
                            help="Hour of the day (0-24) when the digest runs.")
    timezone = fields.Selection(_tz_get, required=True,
                                default=lambda self: self.env.user.tz or "UTC")

    # Audience
    digest_mode = fields.Selection([
        ("company", "Company-wide only"),
        ("per_user", "Per-user only"),
        ("both", "Both"),
    ], default="both", required=True, tracking=True)

    company_recipient_ids = fields.Many2many("res.users",
                                             string="Company digest recipients",
                                             domain="[('company_ids', 'in', company_id)]")

    user_group_id = fields.Many2one("res.groups",
                                    string="Users to include (per-user mode)",
                                    default=lambda self: self.env.ref("pulse_digest.group_pulse_recipient"))

    # Detectors
    detector_line_ids = fields.One2many(
        "pulse.config.detector", "config_id",
        string="Detectors")

    # Reporting
    run_ids = fields.One2many("pulse.run", "config_id")
    last_run_date = fields.Datetime(compute="_compute_last_run", store=True)

    _company_uniq = models.Constraint(
        "UNIQUE(company_id)", "Only one Pulse config per company.")

    @api.depends("run_ids.status", "run_ids.finished_at")
    def _compute_last_run(self):
        for config in self:
            successful = config.run_ids.filtered(
                lambda r: r.status == "done" and r.finished_at
            )
            config.last_run_date = max(
                successful.mapped("finished_at"),
                default=False,
            )

    def _same_local_hour(self, dt_a, dt_b):
        tz = pytz.timezone(self.timezone or "UTC")
        a = pytz.utc.localize(dt_a).astimezone(tz)
        b = pytz.utc.localize(dt_b).astimezone(tz)
        return (a.date(), a.hour) == (b.date(), b.hour)

    def _get_duplicate_runs(self, audience, user=None):
        self.ensure_one()
        now_utc = fields.Datetime.now()
        duplicates = self.run_ids.filtered(
            lambda r: r.audience == audience
            and r.user_id.id == (user.id if user else False)
            and r.started_at
            and self._same_local_hour(r.started_at, now_utc)
        )
        return duplicates

    def run_digest(self, audience, user=None, force=False):
        """Execute all active, available detectors for one audience and persist
        the results as a pulse.run + pulse.run.line records."""
        self.ensure_one()

        if not force:
            duplicate_runs = self._get_duplicate_runs(audience, user)
            if duplicate_runs:
                # already ran this hour, return the existing run
                return duplicate_runs[0]

        company = user.company_id if user else self.company_id
        scope = Scope.user(user) if user else Scope.company(company)

        run = self.env["pulse.run"].create({
            "config_id": self.id,
            "audience": audience,
            "user_id": user.id if user else False,
        })

        lines = self.detector_line_ids.filtered(
            lambda l: l.active and l.detector_id.is_available)

        for line in lines:
            detector_id = line.detector_id
            detector_cls = detector_id._get_detector_class()
            params = {**detector_id.default_params, **line.params}
            detector = detector_cls(params=params)
            for finding in detector.compute(self.env, scope):
                self.env["pulse.run.line"].create({
                    "run_id": run.id,
                    "detector_id": detector_id.id,
                    "res_model": finding.res_model,
                    "res_id": finding.res_id,
                    "res_name": finding.res_name,
                    "severity": finding.severity,
                    "summary": finding.summary,
                    "detail": finding.detail,
                    "metric_value": finding.metric_value or 0.0,
                    "baseline_value": finding.baseline_value or 0.0,
                    "deviation": finding.deviation or 0.0,
                })

        run.write({
            "status": "done",
            "finished_at": fields.Datetime.now(),
            "duration_ms": int((fields.Datetime.now() - run.started_at).total_seconds() * 1000),
        })
        return run

    def run_all_audiences(self, force=False):
        """Make all runs for digest_mode."""
        self.ensure_one()
        if self.digest_mode in ("company", "both"):
            self.run_digest("company", force=force)
        if self.digest_mode in ("per_user", "both"):
            for user in self.user_group_id.user_ids:
                self.run_digest("user", user=user, force=force)

    def _cron_is_due(self, now_utc):
        """True if `now_utc` falls in this config's scheduled hour, in its own
        timezone, AND no run has already fired during that same local hour.
        Cron runs hourly, so we can only resolve to hour granularity — a
        run_time of 7.5 (7:30) is treated as "due during the 7:00-7:59 hour,"
        same as 7.0. Documented limitation, not a bug."""
        self.ensure_one()
        tz = pytz.timezone(self.timezone or "UTC")
        local_now = pytz.utc.localize(now_utc).astimezone(tz)
        if local_now.hour != int(self.run_time):
            return False

        if self.last_run_date:
            if self._same_local_hour(self.last_run_date, now_utc):
                return False  # already ran this hour
        return True

    def _cron_run_digests(self):
        """Entry point for cron_pulse_run_digests (data/pulse_cron_data.xml).
        One hourly cron serves every company: each active config decides for
        itself whether it's due, based on its own run_time/timezone."""
        now_utc = fields.Datetime.now()
        for config in self.search([("active", "=", True)]):
            if config._cron_is_due(now_utc):
                config.run_all_audiences()

    def _runs_action(self, domain_extra=None):
        """Single source of truth for 'open this config's pulse.run records.'
        Used by every action method that ends by showing the run(s) it
        triggered (or, for action_view_runs, without triggering anything)."""
        domain = [("config_id", "=", self.id)]
        if domain_extra:
            domain += domain_extra
        return {
            "type": "ir.actions.act_window",
            "name": "Pulse Runs",
            "res_model": "pulse.run",
            "view_mode": "list,form",
            "domain": domain,
        }

    def action_view_runs(self):
        """History button — same view/domain the other two redirect to,
        without triggering a run."""
        self.ensure_one()
        return self._runs_action()

    def action_run_now(self, audience=None):
        """Manual trigger from the UI — always runs, bypassing the hourly
        dedup that's meant for the automatic cron path."""
        self.ensure_one()
        if audience not in (None, "company"):
            raise ValueError(
                f"action_run_now does not support audience={audience!r}")

        if not audience:
            self.run_all_audiences(force=True)
        else:
            self.run_digest(audience, force=True)

        return self._runs_action()

    def action_admin_run_now(self, audience=None, user_id=None):
        """Admin-only manual trigger. Unlike action_run_now (company-wide only),
        this supports targeting one specific user's per-user digest — e.g. an
        admin resending a single user's run without re-triggering everyone
        else's."""
        self.ensure_one()
        if audience not in (None, "company", "user"):
            raise ValueError(
                f"action_admin_run_now does not support audience={audience!r}")

        if audience == "user":
            if not user_id:
                raise ValueError("audience='user' requires a user_id")
            user = self.env["res.users"].browse(user_id)
            if not user.exists():
                raise ValueError(f"No res.users with id={user_id!r}")
            self.run_digest("user", user=user, force=True)
        elif audience == "company":
            self.run_digest("company", force=True)
        else:
            self.run_all_audiences(force=True)

        domain = [("config_id", "=", self.id)]
        if audience == "user":
            domain.append(("user_id", "=", user_id))

        return self._runs_action()
