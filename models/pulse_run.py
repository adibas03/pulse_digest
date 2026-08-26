from odoo import models, fields, api


class PulseRun(models.Model):
    _name = "pulse.run"
    _description = "Pulse Run"
    _order = "started_at DESC"

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
