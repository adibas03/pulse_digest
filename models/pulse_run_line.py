from odoo import models, fields
from .constants import SEVERITY_SELECTION, SEVERITY_INFO


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

    summary = fields.Char(required=True)
    detail = fields.Text()

    # Metric values for statistical detectors
    metric_value = fields.Float()
    baseline_value = fields.Float()
    deviation = fields.Float(
        help="How many standard deviations from baseline.")
