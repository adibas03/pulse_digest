from odoo import models, fields, api

from .constants import SEVERITY_ORDER as _SEVERITY_ORDER


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

    # Delivery state per channel
    email_sent = fields.Boolean()
    inapp_sent = fields.Boolean()
    whatsapp_sent = fields.Boolean()

    @api.depends("line_ids")
    def _compute_line_count(self):
        for run in self:
            run.line_count = len(run.line_ids)

    def _render_digest_body(self):
        """Findings grouped by severity, as a plain HTML fragment.

        Stand-in for the full portal-page rendering the original spec
        planned (views/pulse_portal_templates.xml, deferred — see
        pulse_digest_spec.md §14). This is deliberately minimal: enough to
        actually deliver real content via email/in-app now, without pulling
        in the portal page's scope. Reused by EmailChannel and InAppChannel
        so the findings list is only rendered once per run.
        """
        self.ensure_one()
        from markupsafe import Markup, escape

        if not self.line_ids:
            return Markup("<p>No findings for this run.</p>")

        lines = self.line_ids.sorted(
            key=lambda l: _SEVERITY_ORDER.get(l.severity, 99))

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
        """Backend URL to this run's form view. Stand-in for a portal URL
        (no /my/pulse/<run_id> page exists yet — see _render_digest_body's
        docstring) — points recipients at the backend record instead, which
        works for anyone with backend access even if it's not the polished
        portal experience the spec envisioned."""
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url")
        return f"{base_url}/odoo/pulse.run/{self.id}"
