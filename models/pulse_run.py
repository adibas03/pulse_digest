from odoo import models, fields, api

from .constants import (
    SEVERITY_SELECTION,
    SEVERITY_DISPLAY_ORDER,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    SEVERITY_CRITICAL,
)


class PulseRun(models.Model):
    _name = "pulse.run"
    _description = "Pulse Run"
    _order = "started_at DESC"
    # Needed so channel dispatch can post to the chatter (InAppChannel) and
    # so runs get standard mail.thread affordances (followers, log messages).
    _inherit = ["mail.thread"]

    config_id = fields.Many2one(
        "pulse.config", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="config_id.company_id", store=True)

    audience = fields.Selection([
        ("company", "Company-wide"),
        ("user", "Per-user"),
    ], required=True)
    user_id = fields.Many2one("res.users",
                              help="The user this run was scoped to (if audience='user').")

    started_at = fields.Datetime(default=fields.Datetime.now)
    finished_at = fields.Datetime()
    duration_ms = fields.Integer()
    status = fields.Selection([
        ("running", "Running"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], default="running")
    error_message = fields.Text()

    line_ids = fields.One2many("pulse.run.line", "run_id")
    line_count = fields.Integer(compute="_compute_line_count", store=True)
    critical_count = fields.Integer(compute="_compute_severity_stats", store=True)
    warning_count = fields.Integer(compute="_compute_severity_stats", store=True)
    info_count = fields.Integer(compute="_compute_severity_stats", store=True)
    worst_severity = fields.Selection(
        SEVERITY_SELECTION, compute="_compute_severity_stats", store=True,
        help="Highest severity among this run's findings; used to color the run in list views.")

    # Delivery state per channel
    email_sent = fields.Boolean()
    inapp_sent = fields.Boolean()
    whatsapp_sent = fields.Boolean()

    @api.depends("line_ids")
    def _compute_line_count(self):
        for run in self:
            run.line_count = len(run.line_ids)

    @api.depends("line_ids.severity")
    def _compute_severity_stats(self):
        for run in self:
            lines = run.line_ids
            run.critical_count = len(lines.filtered(lambda l: l.severity == SEVERITY_CRITICAL))
            run.warning_count = len(lines.filtered(lambda l: l.severity == SEVERITY_WARNING))
            run.info_count = len(lines.filtered(lambda l: l.severity == SEVERITY_INFO))
            run.worst_severity = (
                SEVERITY_CRITICAL if run.critical_count else
                SEVERITY_WARNING if run.warning_count else
                SEVERITY_INFO if run.info_count else False
            )

    def _render_digest_body(self):
        """Findings grouped by severity, worst-first, as a plain HTML fragment.

        Deliberately minimal — no portal page is planned (recipients are
        internal Odoo users with backend access; see pulse_digest_spec.md
        §14). Reused by EmailChannel and InAppChannel so the findings list
        is only rendered once per run.
        """
        self.ensure_one()
        from markupsafe import Markup, escape

        if not self.line_ids:
            return Markup("<p>No findings for this run.</p>")

        lines = self.line_ids.sorted(
            key=lambda l: SEVERITY_DISPLAY_ORDER.get(l.severity, 99))

        rows = Markup("").join(
            Markup(
                '<li style="margin-bottom:8px;">'
                '<strong>[{}]</strong> {}'
                "</li>"
            ).format(line.severity.upper(), escape(line.summary))
            for line in lines
        )
        return Markup('<ul style="list-style:none;padding:0;margin:0;">{}</ul>').format(rows)

    def get_run_url(self):
        """Backend URL to this run's form view — the intended way recipients
        view a run's findings (see _render_digest_body's docstring); no
        portal page is planned for this module."""
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url")
        return f"{base_url}/odoo/pulse.run/{self.id}"
