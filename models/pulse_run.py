from odoo import models, fields, api
from odoo.exceptions import AccessError

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
    mail_count = fields.Integer(compute="_compute_mail_count")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for run in self:
            run.line_count = len(run.line_ids)

    def _compute_mail_count(self):
        # No stored relation from pulse.run to mail.mail — EmailChannel.
        # send() creates mail.mail via mail.template.send_mail() without
        # posting a linked chatter message, so these are otherwise only
        # visible by searching mail.mail directly. Recomputed fresh on
        # every read (no api.depends fields) — standard for a smart-button
        # count over records with no relational field to depend on.
        Mail = self.env["mail.mail"]
        for run in self:
            run.mail_count = Mail.search_count(
                [("model", "=", "pulse.run"), ("res_id", "=", run.id)])

    def action_view_sent_mails(self):
        """Smart-button target: every mail.mail this run generated via
        EmailChannel, per recipient — the actual delivery record (email_to,
        state, failure_reason), not just the run-level email_sent flag."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sent Emails",
            "res_model": "mail.mail",
            "view_mode": "list,form",
            "domain": [("model", "=", "pulse.run"), ("res_id", "=", self.id)],
        }

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

    def _filter_lines_readable_by(self, recipient):
        """Findings whose underlying (res_model, res_id) record `recipient`
        can actually read — the render-time access re-check pulse_digest_
        spec.md §8.3 calls for, so a digest never names/describes a record
        the recipient has no business seeing (e.g. a company-wide run
        naming a crm.lead belonging to a colleague under a standard "Own
        Documents Only" Sales access restriction). Applies uniformly to
        every recipient regardless of how they were resolved — hand-picked
        company_recipient_ids, recipient_group_ids members, or a per-user
        run's own owner — rather than special-casing any of them; for the
        run's own owner this is a harmless no-op in practice, since
        apply_user_scope already limits a per-user run to records that
        owner is assigned to.

        Batched by res_model (one search() per distinct model present,
        evaluated as `recipient`) rather than one check per line — a
        company-wide run can go to many recipients (e.g. a whole sales
        team) and this keeps the cost at recipients x distinct_models, not
        recipients x findings.
        """
        self.ensure_one()
        recipient_env = self.env(user=recipient)

        by_model = {}
        for line in self.line_ids:
            by_model.setdefault(line.res_model, self.env["pulse.run.line"])
            by_model[line.res_model] |= line

        visible = self.env["pulse.run.line"]
        for res_model, model_lines in by_model.items():
            try:
                accessible_ids = set(
                    recipient_env[res_model].search(
                        [("id", "in", model_lines.mapped("res_id"))]).ids)
            except (KeyError, AccessError):
                # KeyError: res_model no longer a registered model (stale
                # finding). AccessError: recipient has no read access to
                # this model at all. Either way, skip this model's lines.
                continue
            visible |= model_lines.filtered(
                lambda l: l.res_id in accessible_ids)
        return visible

    def _render_digest_body(self, lines):
        """Findings grouped by severity, worst-first, as a plain HTML fragment.

        `lines` must be the access-filtered subset a specific recipient is
        allowed to see (via _filter_lines_readable_by) — no default/
        fallback to self.line_ids. A caller forgetting to filter first
        should get a loud TypeError, not a silent unfiltered render; that
        would defeat the whole point of the access re-check.

        Deliberately minimal — no portal page is planned (recipients are
        internal Odoo users with backend access; see pulse_digest_spec.md
        §14). Called once per recipient (see _dispatch_run), not once per
        run, since different recipients can see different subsets.
        """
        self.ensure_one()
        from markupsafe import Markup, escape

        hidden_count = len(self.line_ids) - len(lines)

        if not lines:
            if hidden_count:
                return Markup(
                    "<p>No findings visible to you in this run "
                    "({} not shown — access restricted).</p>"
                ).format(hidden_count)
            return Markup("<p>No findings for this run.</p>")

        lines = lines.sorted(
            key=lambda l: SEVERITY_DISPLAY_ORDER.get(l.severity, 99))

        rows = Markup("").join(
            Markup(
                '<li style="margin-bottom:8px;">'
                '<strong>[{}]</strong> {}'
                "</li>"
            ).format(line.severity.upper(), escape(line.summary))
            for line in lines
        )
        body = Markup('<ul style="list-style:none;padding:0;margin:0;">{}</ul>').format(rows)
        if hidden_count:
            body += Markup(
                '<p style="color:#7f8c8d;font-size:12px;margin-top:12px;">'
                '{} additional finding(s) not shown (access restricted).</p>'
            ).format(hidden_count)
        return body

    def get_run_url(self):
        """Backend URL to this run's form view — the intended way recipients
        view a run's findings (see _render_digest_body's docstring); no
        portal page is planned for this module."""
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param(
            "web.base.url")
        return f"{base_url}/odoo/pulse.run/{self.id}"
