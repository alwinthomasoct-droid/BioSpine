"""
Staff-only analytics views.  Only users with is_staff=True (i.e. Django admin
accounts you create with `python manage.py createsuperuser`) can open them.
Regular BioSpine app users can never reach these URLs.
"""
import csv
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.http import require_POST
from django.utils import timezone

from . import analytics, analytics2, reports
from .models import PostureSession, Review, UserProfile

staff_only = staff_member_required(login_url="/admin/login/")


def _tz(request):
    """Charts/heatmap hours are shown in this timezone. Override with ?tz=Asia/Kolkata
    (any IANA name) or set ANALYTICS_TIMEZONE in settings.py."""
    name = request.GET.get("tz") or getattr(settings, "ANALYTICS_TIMEZONE", settings.TIME_ZONE)
    try:
        return ZoneInfo(name), name
    except Exception:
        return ZoneInfo("UTC"), "UTC"


def _review_stats():
    from django.db.models import Avg, Count
    a = Review.objects.aggregate(n=Count("id"), avg=Avg("rating"))
    return {"total": a["n"] or 0, "average": round(a["avg"], 1) if a["avg"] else None,
            "shown": Review.objects.filter(show_on_home=True).count()}


# ---------------------------------------------------------------------------
# Tabbed staff area: every tab is its own page so nothing is crowded
# ---------------------------------------------------------------------------
TABS = [("dashboard", "Overview", "analytics_dashboard"), ("users", "Users", "analytics_users"),
        ("engagement", "Engagement", "analytics_engagement"), ("posture", "Posture quality", "analytics_posture"),
        ("time", "Time patterns", "analytics_time"), ("body", "Body & BMI", "analytics_body"),
        ("reviews", "Reviews", "analytics_reviews"), ("reports", "Reports", "analytics_reports")]


def _base_ctx(active, tzname):
    return {"tabs": [(k, label, reverse(name)) for k, label, name in TABS], "active_tab": active, "tzname": tzname,
            "ai_on": bool(settings.AI_ENABLED and settings.GEMINI_API_KEY)}


def _int_param(request, name, allowed, default):
    v = request.GET.get(name, str(default))
    return int(v) if v in allowed else default


@staff_only
def dashboard(request):
    """Tab 1 - Overview: the numbers that matter at a glance."""
    tz, tzname = _tz(request)
    days = _int_param(request, "days", ("7", "14", "30", "60", "90"), 30)
    with timezone.override(tz):
        rows = analytics.user_rows()
        attention = sorted([r for r in rows if r["status"] == "at_risk"], key=lambda r: r["last_active"], reverse=True)[:6]
        stars = sorted([r for r in rows if r["sessions"] >= 3 and r["avg_compliance"] is not None],
                       key=lambda r: r["avg_compliance"], reverse=True)[:6]
        newest = sorted(rows, key=lambda r: r["created_at"], reverse=True)[:6]
        ctx = {**_base_ctx("dashboard", tzname), "days": days, "kpi": analytics.overview(), "review_stats": _review_stats(),
               "attention": attention, "stars": stars, "newest": newest,
               "chart": {"daily": analytics.daily_series(days), "signups": analytics.signup_series(days),
                         "modes": analytics.mode_distribution(), "status": analytics.status_counts()}}
        return render(request, "analytics/dashboard.html", ctx)


@staff_only
def users_page(request):
    """Tab 2 - Users: a card for every person; click one for everything that person sees (and more)."""
    tz, tzname = _tz(request)
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    bmi = request.GET.get("bmi", "")
    sort = request.GET.get("sort", "joined")
    direction = "asc" if request.GET.get("dir") == "asc" else "desc"
    view = "table" if request.GET.get("view") == "table" else "cards"
    with timezone.override(tz):
        rows = analytics2.profile_rows(q=q, status=status, sort=sort, direction=direction)
        if bmi == "none":
            rows = [r for r in rows if r["bmi"] is None]
        elif bmi in ("under", "healthy", "over", "obese"):
            rows = [r for r in rows if r["bmi_key"] == bmi]
        page = Paginator(rows, 24).get_page(request.GET.get("page"))
        for r in page.object_list:
            r["spark_pts"] = analytics2.spark_points(r["spark"])
        keep = {"q": q, "status": status, "bmi": bmi, "sort": sort, "dir": direction, "view": view, "tz": tzname}
        ctx = {**_base_ctx("users", tzname), "page": page, "total_matching": len(rows), "q": q, "status": status, "bmi": bmi,
               "sort": sort, "dir": direction, "view": view, "qs": urlencode({k: v for k, v in keep.items() if v}),
               "statuses": ["active", "at_risk", "dormant", "never"],
               "sorts": [("joined", "Joined"), ("last_active", "Last active"), ("sessions", "Sessions"), ("hours", "Wear time"),
                         ("compliance", "Compliance"), ("deviation", "Avg deviation"), ("alerts", "Alerts"), ("streak", "Streak"),
                         ("bmi", "BMI"), ("email", "Email")]}
        return render(request, "analytics/users.html", ctx)


@staff_only
def user_page(request, user_id):
    """One person's full profile: the same report they see + day by day + time slots + every session."""
    tz, tzname = _tz(request)
    try:
        user = UserProfile.objects.get(pk=user_id)
    except UserProfile.DoesNotExist:
        raise Http404("No such user")
    days = _int_param(request, "days", ("7", "30", "90", "0"), 30)
    with timezone.override(tz):
        data = analytics2.user_profile_context(user, days)
        ctx = {**_base_ctx("users", tzname), "u": user, **data["base"], "rep": data["report"], "p": data,
               "initial": (user.email[:1] or "?").upper(),
               "chart": {"daily": data["daily"], "hourly": data["hourly"], "weekly": data["weekly"],
                         "heatmap": data["heatmap"], "weekdays": data["weekdays"]}}
        return render(request, "analytics/user_detail.html", ctx)


@staff_only
def session_page(request, user_id, session_id):
    """One session in full: when it happened, the lean-angle graph, circle diagrams, alerts and events."""
    tz, tzname = _tz(request)
    try:
        user = UserProfile.objects.get(pk=user_id)
        sess = PostureSession.objects.get(pk=session_id, user=user)
    except (UserProfile.DoesNotExist, PostureSession.DoesNotExist):
        raise Http404("No such session")
    with timezone.override(tz):
        row = analytics2.session_row(sess)
        newer = PostureSession.objects.filter(user=user, date__gt=sess.date).order_by("date").first()
        older = PostureSession.objects.filter(user=user, date__lt=sess.date).order_by("-date").first()
        ctx = {**_base_ctx("users", tzname), "u": user, "s": row, "newer": newer, "older": older,
               "initial": (user.email[:1] or "?").upper()}
        return render(request, "analytics/session_detail.html", ctx)


@staff_only
def engagement_page(request):
    """Tab 3 - Engagement: who comes back, where people drop off."""
    tz, tzname = _tz(request)
    with timezone.override(tz):
        rows = analytics2.profile_rows()
        kpi = analytics.overview()
        daily = analytics.daily_series(30)
        users_with = [r for r in rows if r["sessions"] >= 1]
        returning = sum(1 for r in users_with if r["active_days"] >= 2)
        ctx = {**_base_ctx("engagement", tzname), "kpi": kpi,
               "stickiness": analytics2.stickiness([d["users"] for d in daily], kpi["mau"]),
               "returning_pct": round(100 * returning / len(users_with), 1) if users_with else None,
               "avg_sessions": round(sum(r["sessions"] for r in users_with) / len(users_with), 1) if users_with else None,
               "funnel": analytics2.funnel(rows), "per_user": analytics2.sessions_per_user(rows),
               "cohorts": analytics.retention_cohorts(8), "cohort_cols": list(range(8)),
               "status": analytics.status_counts(),
               "chart": {"daily": daily, "signups": analytics.signup_series(30)},
               "at_risk": sorted([r for r in rows if r["status"] == "at_risk"], key=lambda r: r["last_active"], reverse=True)[:12]}
        return render(request, "analytics/engagement.html", ctx)


@staff_only
def posture_page(request):
    """Tab 4 - Posture quality across everyone."""
    tz, tzname = _tz(request)
    with timezone.override(tz):
        pc = analytics2.platform_context(tzname)
        kpi = analytics.overview()
        sess = pc["sessions"]
        good = round(100 * sum(1 for s in sess if s["comp"] >= analytics2.GOOD) / len(sess), 1) if sess else None
        names = dict(UserProfile.objects.values_list("id", "email"))
        tr = pc["trends"]
        for key in ("improving", "declining"):
            for r in tr[key]:
                r["email"] = names.get(r["uid"], "?")
        hours = kpi["total_hours"] or 0
        ctx = {**_base_ctx("posture", tzname), "kpi": kpi, "good_pct": good,
               "alerts_per_hour": round(kpi["total_alerts"] / hours, 1) if hours else None,
               "dist": analytics.compliance_distribution(), "dev_dist": pc["dev_dist"], "len_dist": pc["len_dist"],
               "trends": tr, "modes": analytics.mode_distribution(),
               "chart": {"quality": pc["quality"], "dist": analytics.compliance_distribution(), "dev": pc["dev_dist"],
                         "len": pc["len_dist"], "modes": analytics.mode_distribution()}}
        return render(request, "analytics/posture.html", ctx)


@staff_only
def time_page(request):
    """Tab 5 - When do people wear it, and when do they slouch?"""
    tz, tzname = _tz(request)
    with timezone.override(tz):
        pc = analytics2.platform_context(tzname)
        hrs = [h for h in pc["hourly"] if (h["minutes"] or 0) >= 30 and h["compliance"] is not None]
        notes = []
        if hrs:
            best, worst = max(hrs, key=lambda h: h["compliance"]), min(hrs, key=lambda h: h["compliance"])
            busy = max(pc["hourly"], key=lambda h: h["minutes"] or 0)
            notes = [f"Busiest hour: {busy['label']} ({busy['minutes']:.0f} wear-minutes).",
                     f"Best posture around {best['label']} ({best['compliance']:.0f}% compliance).",
                     f"Weakest posture around {worst['label']} ({worst['compliance']:.0f}% compliance, average lean {worst['avg_dev']}°)."]
        ctx = {**_base_ctx("time", tzname), "hourly": pc["hourly"], "dayparts": pc["dayparts"], "weekdays": pc["weekdays"],
               "notes": notes, "chart": {"hourly": pc["hourly"], "weekdays": pc["weekdays"], "heatmap": pc["heatmap"]}}
        return render(request, "analytics/time.html", ctx)


@staff_only
def body_page(request):
    """Tab 6 - Height / weight / BMI of the users and how it relates to their posture."""
    tz, tzname = _tz(request)
    with timezone.override(tz):
        rows = analytics2.profile_rows()
        stats = analytics2.body_stats(rows)
        missing = [r for r in rows if r["bmi"] is None][:25]
        scatter = [{"x": r["bmi"], "y": r["avg_compliance"], "email": r["email"]} for r in rows
                   if r["bmi"] is not None and r["avg_compliance"] is not None]
        ctx = {**_base_ctx("body", tzname), "stats": stats, "missing": missing,
               "chart": {"bands": stats["bands"], "hist": stats["hist"], "scatter": scatter}}
        return render(request, "analytics/body.html", ctx)


@staff_only
def reports_page(request):
    """Tab 8 - downloads."""
    tz, tzname = _tz(request)
    with timezone.override(tz):
        rows = analytics.user_rows(sort="email", direction="asc")
    return render(request, "analytics/reports.html", {**_base_ctx("reports", tzname), "users": rows})


@staff_only
def export_users_csv(request):
    """One row per user with every aggregate (no password hash, no token)."""
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="biospine_users.csv"'
    w = csv.writer(resp)
    w.writerow(["user_id", "email", "joined_utc", "status", "mode", "sessions", "active_days",
                "total_seconds", "avg_compliance", "alerts", "avg_deviation_deg",
                "first_session_utc", "last_session_utc", "current_streak", "longest_streak", "ai_chats",
                "height_cm", "weight_kg", "bmi"])
    for r in analytics2.profile_rows():
        w.writerow([r["id"], r["email"], r["created_at"].isoformat(), r["status"], r["mode"],
                    r["sessions"], r["active_days"], r["total_seconds"], r["avg_compliance"],
                    r["alerts"], r["avg_deviation"],
                    r["first_session"].isoformat() if r["first_session"] else "",
                    r["last_active"].isoformat() if r["last_active"] else "",
                    r["current_streak"], r["longest_streak"], r["chats"], r["height_cm"] or "", r["weight_kg"] or "", r["bmi"] or ""])
    return resp


@staff_only
def export_sessions_csv(request):
    """Every raw posture session of every user (streamed row by row, safe for big tables)."""
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="biospine_sessions.csv"'
    w = csv.writer(resp)
    w.writerow(["session_id", "user_id", "email", "date_utc", "duration_seconds",
                "compliance_score", "alert_count", "avg_sagittal_deviation_deg"])
    qs = (PostureSession.objects.select_related("user").order_by("date")
          .values_list("id", "user_id", "user__email", "date", "duration_seconds",
                       "compliance_score", "alert_count", "avg_sagittal_deviation"))
    for row in qs.iterator(chunk_size=2000):
        w.writerow([row[0], row[1], row[2], row[3].isoformat(), *row[4:]])
    return resp


# ---------------------------------------------------------------------------
# v5: documented reports (Excel / PDF) and review moderation
# ---------------------------------------------------------------------------
def _download(data, content_type, filename):
    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@staff_only
def report_user(request, user_id, fmt):
    """Complete report of ONE person: /staff/analytics/user/<id>/report.xlsx  or  .pdf"""
    if fmt not in ("xlsx", "pdf"):
        raise Http404("Choose .xlsx or .pdf")
    tz, tzname = _tz(request)
    try:
        user = UserProfile.objects.get(pk=user_id)
    except UserProfile.DoesNotExist:
        raise Http404("No such user")
    with timezone.override(tz):
        rep = analytics.build_user_report(user, tzname)
    stamp = timezone.localdate().isoformat()
    if fmt == "pdf":
        return _download(reports.user_pdf(rep), "application/pdf", f"biospine_report_user{user.pk}_{stamp}.pdf")
    return _download(reports.user_workbook(rep), XLSX, f"biospine_report_user{user.pk}_{stamp}.xlsx")


@staff_only
def report_platform(request, fmt):
    """Report on ALL users with averages over time: /staff/analytics/report.xlsx  or  .pdf"""
    if fmt not in ("xlsx", "pdf"):
        raise Http404("Choose .xlsx or .pdf")
    tz, tzname = _tz(request)
    weeks = request.GET.get("weeks", "26")
    weeks = int(weeks) if weeks in ("4", "8", "12", "26", "52") else 26
    with timezone.override(tz):
        rep = analytics.build_platform_report(tzname, weeks)
    stamp = timezone.localdate().isoformat()
    if fmt == "pdf":
        return _download(reports.platform_pdf(rep), "application/pdf", f"biospine_all_users_report_{stamp}.pdf")
    return _download(reports.platform_workbook(rep), XLSX, f"biospine_all_users_report_{stamp}.xlsx")


@staff_only
def reviews_page(request):
    """Admin decides which client reviews appear on the public home page."""
    tz, tzname = _tz(request)
    return render(request, "analytics/reviews.html", {**_base_ctx("reviews", tzname), "reviews": Review.objects.select_related("user"),
                                                      "stats": _review_stats()})


@staff_only
@require_POST
def review_toggle(request, review_id):
    try:
        r = Review.objects.get(pk=review_id)
    except Review.DoesNotExist:
        raise Http404("No such review")
    r.show_on_home = request.POST.get("show") == "1"
    r.save(update_fields=["show_on_home"])
    return redirect("analytics_reviews")
