"""Server-rendered pages: legal pages, contact form, email verification, password reset, SEO files, health check."""
import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import mail_admins  # noqa: F401  (kept for easy extension)
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from . import emails
from .auth_utils import client_ip, throttle
from .models import ContactMessage, UserProfile

log = logging.getLogger(__name__)


def _msg(request, title, text, ok=True, status=200):
    return render(request, "pages/message.html", {"title": title, "text": text, "ok": ok}, status=status)


def privacy(request):
    return render(request, "pages/privacy.html")


def terms(request):
    return render(request, "pages/terms.html")


def disclaimer(request):
    return render(request, "pages/disclaimer.html")


@require_http_methods(["GET", "POST"])
def contact(request):
    ctx = {"sent": False, "error": ""}
    if request.method == "POST":
        if request.POST.get("website"):                      # honeypot field: real people leave it empty
            ctx["sent"] = True
        elif not throttle(f"contact:{client_ip(request)}", 5, 3600):
            ctx["error"] = "Too many messages from this network. Please try again later."
        else:
            name = request.POST.get("name", "").strip()[:120]
            email = request.POST.get("email", "").strip()[:254]
            message = request.POST.get("message", "").strip()[:4000]
            from django.core.validators import validate_email
            try:
                validate_email(email)
            except ValidationError:
                ctx["error"] = "Please enter a valid email address."
            else:
                if not name or len(message) < 5:
                    ctx["error"] = "Please fill in your name and a short message."
                else:
                    ContactMessage.objects.create(name=name, email=email, message=message)
                    if settings.CONTACT_EMAIL:
                        emails._send(settings.CONTACT_EMAIL, f"[{settings.SITE_NAME}] message from {name}",
                                     f"From: {name} <{email}>\n\n{message}")
                    ctx["sent"] = True
    return render(request, "pages/contact.html", ctx)


def verify_email(request, token):
    try:
        data = emails.read_verify_token(token)
        user = UserProfile.objects.get(pk=data["u"], email=data["e"])
    except (signing.BadSignature, UserProfile.DoesNotExist, KeyError):
        return _msg(request, "Link not valid", "This confirmation link is invalid or has expired. "
                    "Sign in and press 'Resend verification email'.", ok=False, status=400)
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    return _msg(request, "Email confirmed", "Thank you! Your email address is confirmed. You can close this tab and return to the app.")


@require_http_methods(["GET", "POST"])
def reset_password(request, token):
    try:
        data = emails.read_reset_token(token)
        user = UserProfile.objects.get(pk=data["u"])
        if not emails.reset_token_matches(user, data):
            raise signing.BadSignature("password already changed")
    except (signing.BadSignature, UserProfile.DoesNotExist, KeyError):
        return _msg(request, "Link not valid", "This reset link is invalid, expired or has already been used. "
                    "Request a new one from the sign-in screen.", ok=False, status=400)

    error = ""
    if request.method == "POST":
        p1, p2 = request.POST.get("password", ""), request.POST.get("password2", "")
        if p1 != p2:
            error = "The two passwords do not match."
        else:
            try:
                validate_password(p1, user)
            except ValidationError as err:
                error = " ".join(err.messages)
        if not error:
            user.set_password(p1)
            user.email_verified = True        # they just proved they control this mailbox
            user.save(update_fields=["password_hash", "email_verified"])
            user.tokens.all().delete()        # sign out every device
            return _msg(request, "Password updated", "Your password was changed and all devices were signed out. You can now sign in with the new password.")
    return render(request, "pages/reset_password.html", {"error": error})


def unsubscribe(request, token):
    try:
        data = emails.read_unsub_token(token)
        user = UserProfile.objects.get(pk=data["u"])
    except (signing.BadSignature, UserProfile.DoesNotExist, KeyError):
        return _msg(request, "Link not valid", "This unsubscribe link is not valid.", ok=False, status=400)
    user.weekly_email = False
    user.save(update_fields=["weekly_email"])
    return _msg(request, "Unsubscribed", "You will no longer receive the weekly report. You can switch it back on in Settings.")


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


def robots_txt(request):
    body = ("User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /staff/\nDisallow: /api/\n"
            f"Sitemap: {settings.SITE_URL}/sitemap.xml\n")
    return HttpResponse(body, content_type="text/plain")


def sitemap_xml(request):
    urls = ["/", "/privacy/", "/terms/", "/disclaimer/", "/contact/"]
    items = "".join(f"<url><loc>{settings.SITE_URL}{u}</loc></url>" for u in urls)
    return HttpResponse('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                        f"{items}</urlset>", content_type="application/xml")


def service_worker(request):
    """Served from the site root so the service worker can control the whole site."""
    from django.contrib.staticfiles import finders
    path = finders.find("sw.js")
    with open(path, "rb") as fh:
        resp = HttpResponse(fh.read(), content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    resp["Service-Worker-Allowed"] = "/"
    return resp


def not_found(request, exception=None):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)


@require_http_methods(["GET", "POST"])
def cron_weekly(request):
    """Lets a free external scheduler (e.g. cron-job.org) trigger the weekly report once a week:
    GET /cron/weekly-report/?key=<CRON_SECRET>   (disabled when CRON_SECRET is empty)"""
    import hmac
    from django.core.management import call_command
    given = request.headers.get("X-Cron-Key") or request.GET.get("key", "")
    if not settings.CRON_SECRET or not hmac.compare_digest(given, settings.CRON_SECRET):
        return HttpResponse("forbidden", status=403, content_type="text/plain")
    call_command("send_weekly_reports")
    return HttpResponse("ok", content_type="text/plain")
