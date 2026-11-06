"""python manage.py send_weekly_reports [--dry-run]  ->  emails each opted-in, verified user their last-7-days summary.
Schedule once a week (e.g. Monday 08:00)."""
import datetime as dt

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from biospine_app import emails
from biospine_app.models import PostureSession, UserProfile


class Command(BaseCommand):
    help = "Send the weekly posture report email."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="show who would get an email, send nothing")

    def handle(self, *args, **opts):
        now = timezone.now()
        week, prev = now - dt.timedelta(days=7), now - dt.timedelta(days=14)
        sent = skipped = 0
        users = UserProfile.objects.filter(weekly_email=True, email_verified=True)
        for u in users.iterator():
            if u.last_weekly_email_at and now - u.last_weekly_email_at < dt.timedelta(days=6):
                skipped += 1
                continue
            this = PostureSession.objects.filter(user=u, date__gte=week)
            agg = this.aggregate(n=Count("id"), secs=Sum("duration_seconds"), comp=Avg("compliance_score"))
            if not agg["n"]:
                skipped += 1            # nothing to report: don't nag inactive users
                continue
            before = PostureSession.objects.filter(user=u, date__gte=prev, date__lt=week).aggregate(comp=Avg("compliance_score"))["comp"]
            best = (this.annotate(d=TruncDate("date")).values("d").annotate(c=Avg("compliance_score")).order_by("-c").first())
            stats = {
                "sessions": agg["n"], "hours": (agg["secs"] or 0) / 3600, "compliance": agg["comp"] or 0,
                "compliance_delta": (agg["comp"] - before) if before is not None else None,
                "best_day": best["d"].strftime("%A") if best else "", "streak": u.current_streak,
            }
            if opts["dry_run"]:
                self.stdout.write(f"would email {u.email}: {stats}")
            elif emails.send_weekly_report(u, stats):
                u.last_weekly_email_at = now
                u.save(update_fields=["last_weekly_email_at"])
                sent += 1
        self.stdout.write(self.style.SUCCESS(f"Done. sent={sent} skipped={skipped}"))
