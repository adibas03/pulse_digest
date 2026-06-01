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

    _sql_constraints = [
        ("company_uniq", "UNIQUE(company_id)",
         "Only one Pulse config per company."),
    ]
