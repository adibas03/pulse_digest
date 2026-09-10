import pytz
from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
import logging
from .detectors.base import Scope
from .pulse_channel import CHANNELS

_logger = logging.getLogger(__name__)

# Maps a channel's TECHNICAL_NAME to (the pulse.config field gating it at
# the company level, the res.users field gating it for that recipient).
# One dict, read in one place (_dispatch_run), so adding a new channel
# later is "register it + add one line here," not a scattered change.
_CHANNEL_FIELDS = {
    "email": ("email_enabled", "pulse_email_enabled"),
    "inapp": ("inapp_enabled", "pulse_inapp_enabled"),
    "whatsapp": ("whatsapp_enabled", "pulse_whatsapp_enabled"),
}

_CHANNEL_HELP = ("A recipient also needs this channel enabled in their own "
                 "Preferences for it to actually reach them.")


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
    recipient_group_ids = fields.Many2many(
        "res.groups", string="Recipient groups",
        help="Every member of these groups belonging to the target "
             "company also receives whichever digest is dispatched — "
             "company-wide or per-user runs alike — in addition to that "
             "run's normal recipient(s). If a group spans multiple "
             "companies, only members in the run's own company are "
             "notified. Resolved dynamically at dispatch time: add or "
             "remove someone from the group and their digest membership "
             "follows, no config edit needed.")

    user_group_id = fields.Many2one("res.groups",
                                    string="User Digests to run (per-user mode)",
                                    default=lambda self: self.env.ref("pulse_digest.group_pulse_recipient"))

    # Channels — company-level "does this digest use this channel at all,"
    # separate from each recipient's own pulse_*_enabled preference on
    # res.users (models/res_users.py). _dispatch_run only sends through a
    # channel when BOTH this config allows it AND the recipient personally
    # opted in — either side can veto. E.g. a company with no WhatsApp
    # Business setup can turn it off here regardless of any user's personal
    # preference, without having to edit every user record.
    email_enabled = fields.Boolean(
        default=True, string="Email", help=_CHANNEL_HELP)
    inapp_enabled = fields.Boolean(
        default=True, string="In-App", help=_CHANNEL_HELP)
    whatsapp_enabled = fields.Boolean(
        default=False, string="WhatsApp", help=_CHANNEL_HELP)

    # Detectors
    # context={"active_test": False}: without it, deactivating a detector
    # line (unchecking Active in this list) makes the row vanish from the
    # Detectors tab entirely — Odoo auto-filters any fetch of a model with
    # a field literally named "active" unless the context overrides it.
    # This must be set on the field DEFINITION, not the view's field tag —
    # the view-level context attribute for this is unreliable for x2many
    # fields (a long-standing Odoo issue; fixed in core by having the
    # field's own context take precedence — see odoo/odoo#42784).
    detector_line_ids = fields.One2many(
        "pulse.config.detector", "config_id",
        string="Detectors",
        context={"active_test": False})

    # Reporting
    run_ids = fields.One2many("pulse.run", "config_id")
    last_run_date = fields.Datetime(compute="_compute_last_run", store=True)

    _company_uniq = models.Constraint(
        "UNIQUE(company_id)", "Only one Pulse config per company.")

    @api.constrains("digest_mode", "company_recipient_ids", "recipient_group_ids")
    def _check_company_recipients_set(self):
        # A SQL constraint can't express this — both fields are Many2many,
        # so there's no column on pulse.config itself to CHECK against.
        for config in self:
            if config.digest_mode not in ("company", "both"):
                continue  # company-wide dispatch isn't active; nothing to enforce
            if not config.company_recipient_ids and not config.recipient_group_ids:
                raise ValidationError(_(
                    "Company-wide digest mode is enabled, but no company "
                    "recipients are set — add at least one recipient user "
                    "or group, or switch digest mode to per-user only."))

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

    def _suppression_gate(self, detector_cls, finding):
        """v1 suppression: branches on SUPPRESSIBLE/AGE_FIELD, but without a
        per-recipient state store (pulse.finding.state, v1.1) there's nothing to
        check history against yet, so every branch still delivers. v1.1 replaces
        the last branch with a real lookup once that store exists."""
        if not detector_cls.SUPPRESSIBLE:
            return True  # detector doesn't participate in suppression at all

        if detector_cls.AGE_FIELD is None:
            return True  # opted in, but no "since" signal to suppress against

        # SUPPRESSIBLE and has an AGE_FIELD — this is the v1.1 seam: real
        # suppression logic (pulse.finding.state lookup) belongs here.
        return True

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

        run = None
        try:

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
                params = {**(detector_id.default_params or {}),
                          **(line.params or {})}
                detector = detector_cls(params=params)
                for finding in detector.compute(self.env, scope):
                    if not self._suppression_gate(detector_cls, finding):
                        continue
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
        except Exception as e:
            # run can be None here if pulse.run.create() itself is what
            # raised (e.g. an AccessError) — nothing to mark failed in that
            # case, just let the original exception propagate.
            if run:
                run.write({
                    "status": "failed",
                    "error_message": str(e),
                    "finished_at": fields.Datetime.now(),
                })
            raise

        # recipient_group_ids applies to any run, regardless of audience —
        # it decouples "whose records this run is scoped to" from "who
        # receives it": a per-user run's owner still gets their own digest,
        # but the group's current members are forwarded the same thing
        # (e.g. a salesperson's run also reaching their team while they're
        # out). Filtered to the run's own company (`company`, computed
        # above) since group membership isn't company-scoped in Odoo the
        # way company_recipient_ids's domain already restricts individual
        # users — without this, a group spanning multiple companies could
        # leak this run's company's data to an unrelated company's users.
        # Both sides of every union below are always valid (possibly
        # empty) recordsets — never None — so this is safe even when a
        # field is empty; the save-time constraint above is what actually
        # guarantees company-wide mode has at least one recipient.
        recipient_group_users = self.recipient_group_ids.all_user_ids.filtered(
            lambda u: company in u.company_ids)
        if user:
            recipients = user | recipient_group_users
        else:
            recipients = self.company_recipient_ids | recipient_group_users
        self._dispatch_run(run, recipients)
        return run

    def _dispatch_run(self, run, recipients):
        """Send `run`'s digest to each recipient via whichever channels are
        allowed for BOTH this config and that recipient — either side can
        veto a channel: this config's email_enabled/inapp_enabled/
        whatsapp_enabled says whether the digest uses that channel at all,
        and the recipient's own pulse_*_enabled preference (res.users) says
        whether they personally want it.

        Only called after a run finishes successfully (run_digest doesn't
        reach this line if the try/except above re-raised), and only when
        there's something to report — an empty digest isn't sent. One
        recipient's or one channel's failure is logged and skipped rather
        than raised, so it can't take down the others or the run itself;
        run_digest already returned a successful, "done" run by this point.
        """
        self.ensure_one()
        if not run.line_ids:
            return

        body_html = run._render_digest_body()
        subject = "Pulse Digest — {}".format(
            run.started_at.strftime("%Y-%m-%d") if run.started_at else "")

        for recipient in recipients:
            for technical_name, (config_field, pref_field) in _CHANNEL_FIELDS.items():
                if not getattr(self, config_field, False):
                    continue  # this config's digest doesn't use this channel
                if not getattr(recipient, pref_field, False):
                    continue  # recipient personally opted out
                channel = CHANNELS.get(technical_name)
                if not channel or not channel.is_available(self.env):
                    continue
                try:
                    channel.send(self.env, recipient, run, body_html, subject)
                    sent_field = {"email": "email_sent", "inapp": "inapp_sent",
                                  "whatsapp": "whatsapp_sent"}[technical_name]
                    run[sent_field] = True
                except Exception:
                    _logger.exception(
                        "Pulse channel %r failed for run %s, recipient %s",
                        technical_name, run.id, recipient.id)

    def run_all_audiences(self, force=False):
        """Make all runs for digest_mode."""
        self.ensure_one()
        if self.digest_mode in ("company", "both"):
            self.run_digest("company", force=force)
        if self.digest_mode in ("per_user", "both"):
            for user in self.user_group_id.all_user_ids:
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
                try:
                    config.run_all_audiences()
                except Exception:
                    _logger.exception(
                        "Pulse run failed for config %s", config.id)

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

        domain_extra = [("user_id", "=", user_id)
                        ] if audience == "user" else None

        return self._runs_action(domain_extra)
