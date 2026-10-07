from odoo import models, fields, api
from .constants import SEVERITY_SELECTION, SEVERITY_INFO, SEVERITY_DISPLAY_ORDER


class PulseRunLine(models.Model):
    _name = "pulse.run.line"
    _description = "Pulse Run Finding"

    run_id = fields.Many2one("pulse.run", required=True, ondelete="cascade")
    detector_id = fields.Many2one("pulse.detector", required=True)

    # The record this finding points to
    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    res_name = fields.Char(help="Cached display name of the record.")

    # Severity & display
    severity = fields.Selection(
        SEVERITY_SELECTION, default=SEVERITY_INFO)
    severity_sequence = fields.Integer(
        compute="_compute_severity_sequence", store=True,
        help="Worst-first sort key (critical=0, info=2) for the findings list view.")

    summary = fields.Char(required=True)
    detail = fields.Text()

    # Metric values for statistical detectors
    metric_value = fields.Float()
    baseline_value = fields.Float()
    deviation = fields.Float(
        help="How many standard deviations from baseline.")

    @api.depends("severity")
    def _compute_severity_sequence(self):
        for line in self:
            line.severity_sequence = SEVERITY_DISPLAY_ORDER.get(line.severity, 99)
