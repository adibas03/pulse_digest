# models/pulse_channel.py

class PulseChannel:
    """Base class for delivery channels."""
    TECHNICAL_NAME = None  # 'email', 'inapp', 'whatsapp'

    def is_available(self, env):
        """Return True if this channel can be used in the current environment."""
        return True

    def send(self, env, recipient, run, body_html, subject):
        raise NotImplementedError


class EmailChannel(PulseChannel):
    TECHNICAL_NAME = "email"

    def send(self, env, recipient, run, body_html, subject):
        template = env.ref("pulse_digest.mail_template_pulse_digest")
        base_url = env["ir.config_parameter"].sudo().get_param("web.base.url")
        # base.action_res_users_my is the same action the "Preferences" menu
        # item (avatar menu -> My Profile) opens — the self-service dialog
        # views/pulse_user_preferences_views.xml extends with the channel
        # fields, so this deep-links straight to the right place.
        preferences_url = f"{base_url}/odoo/action-base.action_res_users_my"
        template.with_context(
            body_html=body_html,
            subject=subject,
            preferences_url=preferences_url,
        ).send_mail(run.id, email_values={"email_to": recipient.email})


class InAppChannel(PulseChannel):
    TECHNICAL_NAME = "inapp"

    def send(self, env, recipient, run, body_html, subject):
        # Post a mail.message to the user's inbox via the run record
        run.message_post(
            partner_ids=[recipient.partner_id.id],
            subject=subject,
            body=body_html,
            message_type="notification",
            subtype_xmlid="mail.mt_comment",
        )


class WhatsAppChannel(PulseChannel):
    """WhatsApp delivery via Odoo's whatsapp.composer.

    The correct API (odoo/odoo@19.0): create a whatsapp.composer record with
    context pointing at the active model/ids, then call
    action_send_whatsapp_template(). Free-text variables are set via typed
    fields on the composer (free_text_1, free_text_2, ...), not a
    template_variables dict — a `whatsapp.template._send_message(...)`
    method does not exist.

    Pre-approved template setup is a deployment concern, not something this
    module can seed automatically (Meta Business requires manual template
    approval):
      1. Admin creates a whatsapp.template in the WhatsApp app pointing at
         pulse.run as the model, with two free-text variables (link, count).
      2. The template's XML id is stored in ir.config_parameter as
         pulse_digest.whatsapp_template_xmlid, so admins can swap templates
         without code changes. Nothing is sent until this is configured.
    """
    TECHNICAL_NAME = "whatsapp"

    def is_available(self, env):
        # WhatsApp is Odoo 19+. Check the composer model, not the template
        # model — both exist on 19, but composer is what we actually use.
        return "whatsapp.composer" in env

    def send(self, env, recipient, run, body_html, subject):
        if not recipient.pulse_phone:
            return
        template_xmlid = env["ir.config_parameter"].sudo().get_param(
            "pulse_digest.whatsapp_template_xmlid")
        if not template_xmlid:
            return
        template = env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return

        composer = env["whatsapp.composer"].with_context(
            active_model="pulse.run",
            active_ids=run.ids,
        ).create({
            "res_model": "pulse.run",
            "res_ids": str(run.ids),
            "wa_template_id": template.id,
            # get_run_url() is the intended link — no portal page exists or
            # is planned (see PulseRun docstrings); recipients are internal
            # users with backend access, so the backend URL is the design.
            "free_text_1": run.get_run_url(),
            "free_text_2": str(len(run.line_ids)),
        })
        composer.action_send_whatsapp_template()


# Registry — populated at module init
CHANNELS = {}


def register_channel(cls):
    CHANNELS[cls.TECHNICAL_NAME] = cls()
    return cls


register_channel(EmailChannel)
register_channel(InAppChannel)
register_channel(WhatsAppChannel)
