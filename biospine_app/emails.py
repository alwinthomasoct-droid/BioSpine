"""Verification, password-reset and weekly-report emails. Links are signed, expire, and cannot be forged."""
import hashlib
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

log = logging.getLogger(__name__)

VERIFY_SALT = "biospine.verify.v1"
RESET_SALT = "biospine.reset.v1"
UNSUB_SALT = "biospine.unsub.v1"


def make_verify_token(user):
    return signing.dumps({"u": user.pk, "e": user.email}, salt=VERIFY_SALT)


def read_verify_token(token, max_age=3 * 24 * 3600):
    return signing.loads(token, salt=VERIFY_SALT, max_age=max_age)


def _pw_fingerprint(user):
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


def make_reset_token(user):
    # includes a fingerprint of the current password hash -> the link stops working once the password changes
    return signing.dumps({"u": user.pk, "p": _pw_fingerprint(user)}, salt=RESET_SALT)


def read_reset_token(token, max_age=3600):
    return signing.loads(token, salt=RESET_SALT, max_age=max_age)


def reset_token_matches(user, payload):
    return payload.get("p") == _pw_fingerprint(user)


def make_unsub_token(user):
    return signing.dumps({"u": user.pk}, salt=UNSUB_SALT)


def read_unsub_token(token):
    return signing.loads(token, salt=UNSUB_SALT, max_age=365 * 24 * 3600)


def _send(to, subject, text, html_body=None, raise_errors=False):
    """Returns True when the mail server accepted the message. A mail problem never breaks sign-up
    (unless raise_errors=True, which the `check_email` command uses to show the real reason)."""
    try:
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
        if html_body:
            msg.attach_alternative(html_body, "text/html")
        msg.send()
        if not getattr(settings, "EMAIL_CONFIGURED", True):
            log.warning("EMAIL_HOST is not set: the email to %s was only printed in the log, not delivered.", to)
        return True
    except Exception:
        log.exception("Could not send email to %s", to)
        if raise_errors:
            raise
        return False


def send_test(to):
    return _send(to, f"{settings.SITE_NAME} email test",
                 f"If you can read this, {settings.SITE_NAME} can send email.\n\nSent from {settings.SITE_URL}",
                 _wrap("Email works!", f"<p>If you can read this, {escape(settings.SITE_NAME)} can send email.</p>"), raise_errors=True)


def _wrap(title, body_html):
    logo = f'{settings.SITE_URL.rstrip("/")}/static/img/logo-full-small.png'
    return (f'<div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;background:#0d1626;color:#e6edf7;'
            f'padding:24px;border-radius:12px"><p style="text-align:center;margin:0 0 10px"><img src="{logo}" alt="BioSpine" width="110" height="110" '
            f'style="border-radius:14px"></p><h2 style="margin-top:0;color:#60a5fa">{escape(title)}</h2>{body_html}'
            f'<p style="color:#8899b2;font-size:12px;margin-top:24px">{escape(settings.SITE_NAME)} - posture coaching</p></div>')


def _btn(url, label):
    return (f'<p><a href="{escape(url)}" style="background:#2563eb;color:#fff;padding:12px 20px;border-radius:8px;'
            f'text-decoration:none;font-weight:bold;display:inline-block">{escape(label)}</a></p>'
            f'<p style="font-size:12px;color:#8899b2">If the button does not work, copy this link:<br>{escape(url)}</p>')


def send_verification(user):
    url = f"{settings.SITE_URL}/verify-email/{make_verify_token(user)}/"
    text = f"Welcome to {settings.SITE_NAME}!\n\nConfirm your email address:\n{url}\n\nThe link works for 3 days."
    html = _wrap("Confirm your email", "<p>Welcome! Please confirm your email address to unlock all features.</p>"
                 + _btn(url, "Confirm my email"))
    return _send(user.email, f"Confirm your {settings.SITE_NAME} account", text, html)


def send_password_reset(user):
    url = f"{settings.SITE_URL}/reset-password/{make_reset_token(user)}/"
    text = (f"Someone asked to reset the password for your {settings.SITE_NAME} account.\n\n"
            f"Choose a new password here (valid for 1 hour):\n{url}\n\nIf this was not you, ignore this email.")
    html = _wrap("Reset your password", "<p>Someone asked to reset your password. The link is valid for 1 hour. "
                 "If it was not you, just ignore this email.</p>" + _btn(url, "Choose a new password"))
    return _send(user.email, f"Reset your {settings.SITE_NAME} password", text, html)


def send_weekly_report(user, stats):
    unsub = f"{settings.SITE_URL}/unsubscribe/{make_unsub_token(user)}/"
    arrow = ""
    if stats["compliance_delta"] is not None:
        d = stats["compliance_delta"]
        arrow = f" ({'+' if d >= 0 else ''}{d:.0f} pts vs last week)"
    lines = [
        f"Sessions: {stats['sessions']}",
        f"Time worn: {stats['hours']:.1f} h",
        f"Average compliance: {stats['compliance']:.0f}%{arrow}",
        f"Best day: {stats['best_day']}" if stats.get("best_day") else "",
        f"Current streak: {stats['streak']} day(s)",
    ]
    lines = [l for l in lines if l]
    text = "Your week with BioSpine\n\n" + "\n".join(lines) + f"\n\nKeep going: {settings.SITE_URL}\n\nUnsubscribe: {unsub}"
    rows = "".join(f"<li>{escape(l)}</li>" for l in lines)
    html = _wrap("Your week with BioSpine", f"<ul style='line-height:1.8'>{rows}</ul>{_btn(settings.SITE_URL, 'Open my dashboard')}"
                 f"<p style='font-size:11px;color:#8899b2'><a style='color:#8899b2' href='{escape(unsub)}'>Unsubscribe from weekly emails</a></p>")
    return _send(user.email, "Your weekly posture report", text, html)
