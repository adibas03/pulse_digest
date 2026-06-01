class ResUsers(models.Model):
    _inherit = "res.users"

    pulse_email_enabled = fields.Boolean(default=True)
    pulse_inapp_enabled = fields.Boolean(default=True)
    pulse_whatsapp_enabled = fields.Boolean(default=False)
    pulse_phone = fields.Char(
        help="Phone number for WhatsApp digest delivery (19+).")
