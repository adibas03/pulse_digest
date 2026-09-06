from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PulseRunWizard(models.TransientModel):
    _name = "pulse.run.wizard"
    _description = "Run Pulse Digest Now"

    config_id = fields.Many2one("pulse.config", required=True, ondelete="cascade")
    audience = fields.Selection([
        ("company", "Company-wide"),
        ("user", "Specific user"),
    ], required=True, default="company")
    user_id = fields.Many2one(
        "res.users", string="User",
        domain="[('id', 'in', allowed_user_ids)]",
        help="Restricted to users in this config's 'Users to include (per-user mode)' group.")
    allowed_user_ids = fields.Many2many(
        "res.users", compute="_compute_allowed_user_ids")

    @api.depends("config_id")
    def _compute_allowed_user_ids(self):
        for wizard in self:
            wizard.allowed_user_ids = wizard.config_id.user_group_id.all_user_ids

    def action_run(self):
        self.ensure_one()
        if self.audience == "user" and not self.user_id:
            raise UserError(_("Select a user to run a per-user digest for."))
        return self.config_id.action_admin_run_now(
            audience=self.audience,
            user_id=self.user_id.id if self.audience == "user" else None,
        )
