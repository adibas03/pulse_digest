from odoo import api, models, fields
import importlib


class PulseDetector(models.Model):
    _name = "pulse.detector"
    _description = "Pulse Detector Catalog"
    _order = "category, sequence, name"

    name = fields.Char(required=True, translate=True)
    technical_name = fields.Char(required=True, index=True)
    # Used to look up the Python class. Must be globally unique.
    # Convention: <app>.<detector> e.g. "account.overdue_invoices"

    category = fields.Selection([
        ("accounting", "Accounting"),
        ("sales", "Sales"),
    ], required=True)

    description = fields.Text(translate=True)
    rationale = fields.Text(translate=True,
                            help="Why this detector matters. Shown in the configuration UI.")

    sequence = fields.Integer(default=10)

    detector_class = fields.Char(required=True,
                                 help="Dotted Python path, e.g. "
                                 "odoo.addons.pulse_digest.models.detectors.account.overdue_invoices."
                                 "OverdueInvoicesDetector")

    dependency_modules = fields.Char(
        help="Comma-separated list of Odoo modules this detector requires. "
             "Detector is hidden if any of these are not installed.")

    is_available = fields.Boolean(
        compute="_compute_is_available",
        help="False if any module in dependency_modules is not installed.",
    )

    is_default_enabled = fields.Boolean(default=False,
                                        help="If True, this detector is active by default for new configs.")

    is_statistical = fields.Boolean(default=False,
                                    help="If True, requires baseline data and may be noisy on small samples. "
                                    "Surfaced separately in the UI.")

    default_params = fields.Json(default=dict,
                                 help="Default parameter values. Schema documented per detector.")

    _technical_name_uniq = models.Constraint(
        "UNIQUE(technical_name)", "Detector technical names must be unique.")

    @api.depends("dependency_modules")
    def _compute_is_available(self):
        Module = self.env["ir.module.module"]
        for detector in self:
            modules = [m.strip() for m in (
                detector.dependency_modules or "").split(",") if m.strip()]
            detector.is_available = not modules or Module.search_count([
                ("name", "in", modules), ("state", "=", "installed"),
            ]) == len(modules)

    def _get_detector_class(self):
        self.ensure_one()
        module_path, class_name = self.detector_class.strip().rsplit(".", 1)
        module = importlib.import_module(module_path)

        return getattr(module, class_name)
