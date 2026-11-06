"""python manage.py check_ai   ->   tests your Gemini key and every model in the fallback chain."""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from biospine_app import ai


class Command(BaseCommand):
    help = "Check that the Gemini API key works and show which model answers."

    def handle(self, *args, **opts):
        if not settings.GEMINI_API_KEY:
            self.stderr.write(self.style.ERROR("GEMINI_API_KEY is empty. Put it in your .env file / host settings."))
            return
        self.stdout.write(f"Key found (ends with ...{settings.GEMINI_API_KEY[-4:]}). Trying the full chat path...\n")
        try:
            text, model = ai.chat_reply("My neck feels stiff after work. One quick tip?", 14.0, "Forward Slouch", "62%")
            self.stdout.write(self.style.SUCCESS(f"WORKING with model '{model}'. Sample reply:\n\n{text}\n"))
            return
        except ai.AIError as e:
            self.stdout.write(self.style.ERROR(f"Chat failed [{e.kind}]: {e.detail or e.user_message}\n"))

        self.stdout.write("Asking Google which models your key can use (generateContent)...")
        try:
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                             headers={"x-goog-api-key": settings.GEMINI_API_KEY}, timeout=20)
            if r.status_code != 200:
                self.stdout.write(self.style.ERROR(f"HTTP {r.status_code}: {r.text[:300]}"))
                return
            names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]]
            self.stdout.write("Flash models available to you:\n  " + "\n  ".join(names[:25]))
            self.stdout.write(self.style.WARNING("\nPick one and set it, e.g.  GEMINI_MODEL=" + (names[0] if names else "<name>")))
        except requests.RequestException as exc:
            self.stdout.write(self.style.ERROR(f"Network problem: {exc}"))
