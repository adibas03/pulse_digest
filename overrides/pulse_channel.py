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
        template.with_context(
            body_html=body_html,
            subject=subject,
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
    TECHNICAL_NAME = "whatsapp"

    def is_available(self, env):
        # WhatsApp is Odoo 19+
        return "whatsapp.template" in env

    def send(self, env, recipient, run, body_html, subject):
        if not recipient.pulse_phone:
            return
        # Use a pre-approved template that links to the portal page
        template = env.ref("pulse_digest.whatsapp_template_pulse_digest")
        portal_url = run.get_portal_url()
        template._send_message(
            recipient.pulse_phone,
            template_variables={"portal_url": portal_url,
                                "count": len(run.line_ids)},
        )


# Registry — populated at module init
CHANNELS = {}


def register_channel(cls):
    CHANNELS[cls.TECHNICAL_NAME] = cls()
    return cls


register_channel(EmailChannel)
register_channel(InAppChannel)
register_channel(WhatsAppChannel)
