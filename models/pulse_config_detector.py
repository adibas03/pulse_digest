class PulseConfigDetector(models.Model):
    _name = "pulse.config.detector"
    _description = "Pulse Config Detector"

    config_id = fields.Many2one(
        "pulse.config", required=True, ondelete="cascade")
    detector_id = fields.Many2one(
        "pulse.detector", required=True, ondelete="cascade")

    active = fields.Boolean(default=True)
    params = fields.Json(default=dict,
                         help="Overrides for the detector's default_params.")

    # Convenience computed fields for the UI
    category = fields.Selection(related="detector_id.category", store=True)
    is_statistical = fields.Boolean(
        related="detector_id.is_statistical", store=True)

    _sql_constraints = [
        ("config_detector_uniq", "UNIQUE(config_id, detector_id)",
         "Each detector can only be linked once per config."),
    ]
