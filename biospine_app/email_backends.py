"""Sends e-mail through Brevo's HTTPS API (Render's free plan blocks SMTP ports)."""
import logging
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

log = logging.getLogger(__name__)


class BrevoEmailBackend(BaseEmailBackend):
    endpoint = "https://api.brevo.com/v3/smtp/email"

    def send_messages(self, email_messages):
        sent = 0
        for m in email_messages:
            name, addr = parseaddr(m.from_email or settings.DEFAULT_FROM_EMAIL)
            html = next((body for body, mime in getattr(m, "alternatives", []) if mime == "text/html"), None)
            payload = {"sender": {"name": name or settings.SITE_NAME, "email": addr},
                       "to": [{"email": r} for r in m.to], "subject": m.subject, "textContent": m.body or " "}
            if html:
                payload["htmlContent"] = html
            if m.reply_to:
                payload["replyTo"] = {"email": parseaddr(m.reply_to[0])[1]}
            try:
                resp = requests.post(self.endpoint, json=payload, timeout=15,
                                     headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"})
            except requests.RequestException as exc:
                log.error("Could not reach Brevo: %s", exc)
                if not self.fail_silently:
                    raise
                continue
            if resp.status_code >= 300:
                log.error("Brevo refused the e-mail (HTTP %s): %s", resp.status_code, resp.text[:300])
                if not self.fail_silently:
                    raise RuntimeError(f"Brevo error {resp.status_code}: {resp.text[:200]}")
                continue
            sent += 1
        return sent