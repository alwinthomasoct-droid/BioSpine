"""python manage.py check_email you@example.com   ->  sends a test mail and tells you plainly what is wrong if it fails."""
from django.conf import settings
from django.core.management.base import BaseCommand

from biospine_app import emails


class Command(BaseCommand):
    help = "Send a test email so you can confirm that sign-up / password-reset / weekly emails will really arrive."

    def add_arguments(self, parser):
        parser.add_argument("to", help="address that should receive the test email")

    def handle(self, *args, **opts):
        if not getattr(settings, "EMAIL_CONFIGURED", False):
            self.stdout.write(self.style.WARNING(
                "EMAIL_HOST is empty, so emails are only PRINTED in this terminal / the server log - nobody receives them.\n"
                "Set EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD (and DEFAULT_FROM_EMAIL) to really send mail."))
        else:
            self.stdout.write(f"Server: {settings.EMAIL_HOST}:{settings.EMAIL_PORT}  login: {settings.EMAIL_HOST_USER or '(none)'}  "
                              f"from: {settings.DEFAULT_FROM_EMAIL}  SSL={getattr(settings, 'EMAIL_USE_SSL', False)} TLS={getattr(settings, 'EMAIL_USE_TLS', False)}")
        self.stdout.write(f"Links in emails will point to: {settings.SITE_URL}")
        if "localhost" in settings.SITE_URL or "127.0.0.1" in settings.SITE_URL:
            self.stdout.write(self.style.WARNING("SITE_URL is a local address - set SITE_URL to your real website address, "
                                                 "otherwise the links in verification / reset emails will not open for your users."))
        if not getattr(settings, "EMAIL_CONFIGURED", False):
            self.stdout.write(self.style.ERROR(
                "\nNOT SENT: no email server is configured, so nothing was delivered to " + opts["to"] + ".\n"
                "Fix: put EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD and DEFAULT_FROM_EMAIL in the .env file "
                "that sits next to manage.py (the same folder you run this command in), then run this command again."))
            return
        try:
            emails.send_test(opts["to"])
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"\nFAILED: {type(exc).__name__}: {exc}"))
            self.stdout.write("Common fixes: wrong password (Gmail needs an 'App password'), wrong port "
                              "(587 = TLS, 465 = SSL), or the provider blocks the 'from' address (use your login address).")
            return
        self.stdout.write(self.style.SUCCESS(f"\nThe mail server accepted the test email for {opts['to']}. Check the inbox (and spam)."))
