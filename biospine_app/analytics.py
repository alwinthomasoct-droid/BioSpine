"""
Server-side analytics for BioSpine.

Everything here runs in the database / Django ORM on the server. Nothing is
sent to the browser except already-aggregated numbers, and the views that call
these functions are staff-only (see views_analytics.py).

Sections
  1. Helpers
  2. Platform-wide analytics   (overview, daily series, cohorts, heatmap ...)
  3. Per-user table            (one row per user, sortable / searchable)
  4. Per-user deep dive        (full usage timeline for ONE user)
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate, TruncWeek
from django.utils import timezone

from .models import ChatMessage, PostureSession, UserProfile

ACTIVE_DAYS = 7      # used a session in the last 7 days  -> "active"
AT_RISK_DAYS = 30    # 8-30 days of silence               -> "at_risk"; more -> "dormant"
GOOD_COMPLIANCE = 60  # same threshold the streak logic uses


# ---------------------------------------------------------------------------
# 1. Helpers
# ---------------------------------------------------------------------------
def fmt_duration(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _r(value, nd=1):
    return round(value, nd) if value is not None else None


def user_status(last_active, now=None):
    """Lifecycle label for a user based on their latest session."""
    now = now or timezone.now()
    if last_active is None:
        return "never"
    gap = (now - last_active).days
    if gap <= ACTIVE_DAYS:
        return "active"
    if gap <= AT_RISK_DAYS:
        return "at_risk"
    return "dormant"


def _date_range(days):
    today = timezone.localdate()
    return [today - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]


# ---------------------------------------------------------------------------
# 2. Platform-wide analytics
# ---------------------------------------------------------------------------
def overview():
    now = timezone.now()
    today = timezone.localdate()
    sessions = PostureSession.objects.all()

    def active_since(days):
        since = now - dt.timedelta(days=days)
        return sessions.filter(date__gte=since).values("user_id").distinct().count()

    totals = sessions.aggregate(
        n=Count("id"), secs=Sum("duration_seconds"), comp=Avg("compliance_score"),
        alerts=Sum("alert_count"), dev=Avg("avg_sagittal_deviation"),
    )
    total_users = UserProfile.objects.count()
    users_with_sessions = sessions.values("user_id").distinct().count()
    dau = sessions.filter(date__date=today).values("user_id").distinct().count()
    wau, mau = active_since(7), active_since(30)

    return {
        "total_users": total_users,
        "users_with_sessions": users_with_sessions,
        "activation_rate": _r(100 * users_with_sessions / total_users) if total_users else 0,
        "new_users_7d": UserProfile.objects.filter(created_at__gte=now - dt.timedelta(days=7)).count(),
        "new_users_30d": UserProfile.objects.filter(created_at__gte=now - dt.timedelta(days=30)).count(),
        "dau": dau, "wau": wau, "mau": mau,
        "stickiness": _r(100 * dau / mau) if mau else 0,   # DAU / MAU
        "total_sessions": totals["n"] or 0,
        "total_hours": _r((totals["secs"] or 0) / 3600),
        "avg_compliance": _r(totals["comp"]),
        "total_alerts": totals["alerts"] or 0,
        "avg_deviation": _r(totals["dev"]),
        "avg_session": fmt_duration((totals["secs"] or 0) / totals["n"]) if totals["n"] else "0s",
        "total_chats": ChatMessage.objects.count(),
        "chat_users": ChatMessage.objects.values("user_id").distinct().count(),
        "status_counts": status_counts(),
    }


def status_counts():
    last = {r["user_id"]: r["last"] for r in
            PostureSession.objects.values("user_id").annotate(last=Max("date"))}
    counts = {"active": 0, "at_risk": 0, "dormant": 0, "never": 0}
    now = timezone.now()
    for uid in UserProfile.objects.values_list("id", flat=True):
        counts[user_status(last.get(uid), now)] += 1
    return counts


def daily_series(days=30):
    """Per-day sessions, distinct active users, avg compliance, hours worn, alerts."""
    since = _date_range(days)[0]
    rows = (PostureSession.objects.filter(date__date__gte=since)
            .annotate(d=TruncDate("date")).values("d")
            .annotate(sessions=Count("id"), users=Count("user_id", distinct=True),
                      comp=Avg("compliance_score"), secs=Sum("duration_seconds"),
                      alerts=Sum("alert_count")))
    by_day = {r["d"]: r for r in rows}
    out = []
    for d in _date_range(days):
        r = by_day.get(d)
        out.append({
            "date": d.isoformat(),
            "sessions": r["sessions"] if r else 0,
            "users": r["users"] if r else 0,
            "compliance": _r(r["comp"]) if r else None,
            "hours": _r(r["secs"] / 3600, 2) if r else 0,
            "alerts": r["alerts"] if r else 0,
        })
    return out


def signup_series(days=30):
    since = _date_range(days)[0]
    rows = (UserProfile.objects.filter(created_at__date__gte=since)
            .annotate(d=TruncDate("created_at")).values("d").annotate(n=Count("id")))
    by_day = {r["d"]: r["n"] for r in rows}
    return [{"date": d.isoformat(), "signups": by_day.get(d, 0)} for d in _date_range(days)]


def retention_cohorts(weeks=8):
    """Weekly signup cohorts: % of each cohort that logged a session in week 0,1,2...
    (week 0 = the week they signed up)."""
    today = timezone.localdate()
    this_monday = today - dt.timedelta(days=today.weekday())
    first_monday = this_monday - dt.timedelta(weeks=weeks - 1)

    users = list(UserProfile.objects.filter(created_at__date__gte=first_monday)
                 .values("id", "created_at"))
    if not users:
        return []
    cohort_of = {}
    cohorts = defaultdict(list)
    for u in users:
        d = timezone.localtime(u["created_at"]).date()
        monday = d - dt.timedelta(days=d.weekday())
        cohort_of[u["id"]] = monday
        cohorts[monday].append(u["id"])

    active = defaultdict(set)  # (cohort_monday, week_offset) -> {user_ids}
    for s in PostureSession.objects.filter(user_id__in=list(cohort_of)).values("user_id", "date"):
        d = timezone.localtime(s["date"]).date()
        c = cohort_of[s["user_id"]]
        offset = (d - c).days // 7
        if offset >= 0:
            active[(c, offset)].add(s["user_id"])

    out = []
    for monday in sorted(cohorts):
        size = len(cohorts[monday])
        max_off = (this_monday - monday).days // 7
        cells = []
        for k in range(weeks):
            if k > max_off:
                cells.append(None)  # future week, not observable yet
            else:
                cells.append(_r(100 * len(active[(monday, k)]) / size))
        out.append({"cohort": monday.isoformat(), "size": size, "weeks": cells})
    return out


def usage_heatmap():
    """7 x 24 matrix of session counts (rows Mon..Sun, columns hour of day)
    in the current timezone."""
    grid = [[0] * 24 for _ in range(7)]
    rows = (PostureSession.objects.annotate(wd=ExtractWeekDay("date"), hr=ExtractHour("date"))
            .values("wd", "hr").annotate(n=Count("id")))
    for r in rows:
        row = (r["wd"] + 5) % 7   # Django: 1=Sunday..7=Saturday -> 0=Monday..6=Sunday
        grid[row][r["hr"]] = r["n"]
    return grid


def compliance_distribution():
    buckets = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    labels = ["0-19%", "20-39%", "40-59%", "60-79%", "80-100%"]
    agg = PostureSession.objects.aggregate(**{
        f"b{i}": Count("id", filter=Q(compliance_score__gte=lo, compliance_score__lt=hi))
        for i, (lo, hi) in enumerate(buckets)})
    return [{"label": labels[i], "count": agg[f"b{i}"]} for i in range(len(buckets))]


def mode_distribution():
    rows = UserProfile.objects.values("active_mode").annotate(n=Count("id")).order_by("-n")
    return [{"mode": r["active_mode"], "users": r["n"]} for r in rows]


# ---------------------------------------------------------------------------
# 3. Per-user table (one row per user)
# ---------------------------------------------------------------------------
SORT_KEYS = {
    "email": lambda r: r["email"],
    "joined": lambda r: r["created_at"],
    "last_active": lambda r: r["last_active"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
    "sessions": lambda r: r["sessions"],
    "hours": lambda r: r["total_seconds"],
    "compliance": lambda r: r["avg_compliance"] if r["avg_compliance"] is not None else -1,
    "alerts": lambda r: r["alerts"],
    "streak": lambda r: r["current_streak"],
    "longest": lambda r: r["longest_streak"],
    "chats": lambda r: r["chats"],
    "active_days": lambda r: r["active_days"],
}


def user_rows(q="", status="", sort="joined", direction="desc"):
    now = timezone.now()
    sess = {r["user_id"]: r for r in PostureSession.objects.values("user_id").annotate(
        n=Count("id"), secs=Sum("duration_seconds"), comp=Avg("compliance_score"),
        alerts=Sum("alert_count"), dev=Avg("avg_sagittal_deviation"),
        first=Min("date"), last=Max("date"),
        days=Count(TruncDate("date"), distinct=True))}
    chats = {r["user_id"]: r for r in ChatMessage.objects.values("user_id").annotate(
        n=Count("id"), last=Max("created_at"))}

    users = UserProfile.objects.all()
    if q:
        users = users.filter(email__icontains=q)

    rows = []
    for u in users:
        s, c = sess.get(u.id), chats.get(u.id)
        last = s["last"] if s else None
        row = {
            "id": u.id, "email": u.email, "created_at": u.created_at,
            "mode": u.active_mode,
            "sessions": s["n"] if s else 0,
            "total_seconds": s["secs"] or 0 if s else 0,
            "hours": fmt_duration(s["secs"] if s else 0),
            "avg_compliance": _r(s["comp"]) if s else None,
            "alerts": s["alerts"] or 0 if s else 0,
            "avg_deviation": _r(s["dev"]) if s else None,
            "first_session": s["first"] if s else None,
            "last_active": last,
            "active_days": s["days"] if s else 0,
            "current_streak": u.current_streak, "longest_streak": u.longest_streak,
            "chats": c["n"] if c else 0,
            "status": user_status(last, now),
        }
        if status and row["status"] != status:
            continue
        rows.append(row)

    key = SORT_KEYS.get(sort, SORT_KEYS["joined"])
    rows.sort(key=key, reverse=(direction != "asc"))
    return rows


def top_users(n=10, by="sessions"):
    rows = user_rows(sort=by, direction="desc")
    return rows[:n]


# ---------------------------------------------------------------------------
# 4. Per-user deep dive
# ---------------------------------------------------------------------------
def user_detail(user, timeline_limit=400):
    now = timezone.now()
    sessions = list(user.sessions.order_by("date"))      # oldest -> newest
    chats = list(user.chat_messages.order_by("created_at"))

    n = len(sessions)
    total_secs = sum(s.duration_seconds for s in sessions)
    comp = [s.compliance_score for s in sessions]
    devs = [s.avg_sagittal_deviation for s in sessions]
    active_dates = sorted({timezone.localtime(s.date).date() for s in sessions})

    # longest silence between two sessions
    longest_gap = 0
    for a, b in zip(active_dates, active_dates[1:]):
        longest_gap = max(longest_gap, (b - a).days - 1)

    # is the user improving? compare first 5 vs last 5 sessions
    trend = None
    if n >= 6:
        first5, last5 = comp[:5], comp[-5:]
        trend = _r(sum(last5) / 5 - sum(first5) / 5)

    summary = {
        "email": user.email,
        "joined": user.created_at,
        "account_age_days": (now - user.created_at).days,
        "status": user_status(sessions[-1].date if sessions else None, now),
        "mode": user.active_mode,
        "settings": {"warning_angle": user.warning_angle, "safe_zone": user.safe_zone,
                     "lateral_limit": user.lateral_limit},
        "streak_current": user.current_streak, "streak_longest": user.longest_streak,
        "streak_last_credit": user.last_streak_date,
        "sessions": n,
        "total_time": fmt_duration(total_secs),
        "avg_session": fmt_duration(total_secs / n) if n else "0s",
        "avg_compliance": _r(sum(comp) / n) if n else None,
        "best_compliance": max(comp) if comp else None,
        "worst_compliance": min(comp) if comp else None,
        "good_sessions_pct": _r(100 * sum(c >= GOOD_COMPLIANCE for c in comp) / n) if n else None,
        "total_alerts": sum(s.alert_count for s in sessions),
        "alerts_per_hour": _r(sum(s.alert_count for s in sessions) / (total_secs / 3600)) if total_secs else None,
        "avg_deviation": _r(sum(devs) / n, 2) if n else None,
        "first_session": sessions[0].date if sessions else None,
        "last_session": sessions[-1].date if sessions else None,
        "active_days": len(active_dates),
        "longest_gap_days": longest_gap,
        "compliance_trend": trend,   # +ve = improved
        "chats": len(chats),
    }

    # per-day and per-week series for charts
    per_day = defaultdict(lambda: {"sessions": 0, "secs": 0, "comp": [], "alerts": 0})
    for s in sessions:
        d = timezone.localtime(s.date).date()
        p = per_day[d]
        p["sessions"] += 1
        p["secs"] += s.duration_seconds
        p["comp"].append(s.compliance_score)
        p["alerts"] += s.alert_count
    daily = [{"date": d.isoformat(), "sessions": p["sessions"],
              "minutes": _r(p["secs"] / 60), "compliance": _r(sum(p["comp"]) / len(p["comp"])),
              "alerts": p["alerts"]} for d, p in sorted(per_day.items())]

    weekly = [{"week": r["w"].date().isoformat() if hasattr(r["w"], "date") else str(r["w"]),
               "sessions": r["n"], "hours": _r((r["secs"] or 0) / 3600, 2),
               "compliance": _r(r["comp"]), "alerts": r["alerts"] or 0}
              for r in (user.sessions.annotate(w=TruncWeek("date")).values("w")
                        .annotate(n=Count("id"), secs=Sum("duration_seconds"),
                                  comp=Avg("compliance_score"), alerts=Sum("alert_count"))
                        .order_by("w"))]

    hours = [0] * 24
    for s in sessions:
        hours[timezone.localtime(s.date).hour] += 1

    # unified, newest-first timeline of everything this user did
    events = [{"when": user.created_at, "kind": "account", "title": "Account created", "detail": ""}]
    for s in sessions:
        events.append({
            "when": s.date, "kind": "session",
            "title": f"Posture session - {s.compliance_score}% compliance",
            "detail": f"{fmt_duration(s.duration_seconds)} worn, {s.alert_count} alerts, "
                      f"avg slouch {s.avg_sagittal_deviation:.1f} deg",
            "score": s.compliance_score,
        })
    for c in chats:
        events.append({"when": c.created_at, "kind": "chat", "title": "Asked AI Physio",
                       "detail": c.question[:160]})
    events.sort(key=lambda e: e["when"], reverse=True)

    return {
        "summary": summary, "daily": daily, "weekly": weekly, "hours": hours,
        "timeline": events[:timeline_limit], "timeline_total": len(events),
        "sessions": list(reversed(sessions)),
        "chats": list(reversed(chats)),
    }


# ---------------------------------------------------------------------------
# 5. v5: documented reports (admin) - plain-language insights + averages over time
# ---------------------------------------------------------------------------
def weekly_platform_series(weeks=26):
    """Average behaviour of ALL users, week by week (the 'analysis of all users over time' report)."""
    since = timezone.now() - dt.timedelta(weeks=weeks)
    rows = (PostureSession.objects.filter(date__gte=since).annotate(w=TruncWeek("date")).values("w")
            .annotate(n=Count("id"), users=Count("user_id", distinct=True), secs=Sum("duration_seconds"),
                      comp=Avg("compliance_score"), alerts=Sum("alert_count")).order_by("w"))
    signups = {}
    for u in UserProfile.objects.filter(created_at__gte=since).annotate(w=TruncWeek("created_at")).values("w").annotate(n=Count("id")):
        signups[u["w"].date() if hasattr(u["w"], "date") else u["w"]] = u["n"]
    out = []
    for r in rows:
        wk = r["w"].date() if hasattr(r["w"], "date") else r["w"]
        hours = (r["secs"] or 0) / 3600
        out.append({
            "week": wk.isoformat(), "users": r["users"], "sessions": r["n"],
            "sessions_per_user": _r(r["n"] / r["users"], 2) if r["users"] else 0,
            "hours_per_user": _r(hours / r["users"], 2) if r["users"] else 0,
            "compliance": _r(r["comp"]),
            "alerts_per_hour": _r((r["alerts"] or 0) / hours) if hours else 0,
            "signups": signups.get(wk, 0),
        })
    return out


def user_insights(summary, weekly):
    """A few sentences a non-technical admin can read straight away."""
    out = []
    n = summary["sessions"]
    if not n:
        return ["This person has not recorded any posture session yet."]
    out.append(f"{summary['email']} has recorded {n} session(s) over {summary['active_days']} different day(s), "
               f"wearing the device for {summary['total_time']} in total.")
    comp = summary["avg_compliance"]
    if comp is not None:
        band = "excellent" if comp >= 80 else "good" if comp >= 60 else "needs improvement"
        out.append(f"Average posture compliance is {comp}% ({band}). The best session reached {summary['best_compliance']}% "
                   f"and the lowest was {summary['worst_compliance']}%.")
    t = summary.get("compliance_trend")
    if t is not None:
        out.append("Posture is improving: the latest sessions are %.1f points better than the first ones." % t if t > 1 else
                   "Posture has slipped by %.1f points compared with the first sessions." % abs(t) if t < -1 else
                   "Posture has stayed about the same since the first sessions.")
    if summary["alerts_per_hour"] is not None:
        out.append(f"The device alerted about {summary['alerts_per_hour']} time(s) per hour worn.")
    out.append(f"Current streak: {summary['streak_current']} day(s); longest streak: {summary['streak_longest']} day(s). "
               f"Status: {summary['status'].replace('_', ' ')}.")
    return out


def platform_insights(kpi, weekly):
    out = [f"{kpi['total_users']} people have registered; {kpi['users_with_sessions']} ({kpi['activation_rate']}%) have recorded at least one session.",
           f"In the last 30 days {kpi['mau']} people were active ({kpi['wau']} in the last 7 days).",
           f"Together they have logged {kpi['total_sessions']} sessions and {kpi['total_hours']} hours of wear time "
           f"(average session {kpi['avg_session']})."]
    if kpi["avg_compliance"] is not None:
        out.append(f"The average posture compliance across everyone is {kpi['avg_compliance']}%.")
    comps = [w["compliance"] for w in weekly if w["compliance"] is not None]
    if len(comps) >= 4:
        a, b = sum(comps[:2]) / 2, sum(comps[-2:]) / 2
        out.append(("Over time, the average compliance of all users is rising (%+.1f points between the first and last weeks)." % (b - a)) if b - a > 1 else
                   ("Over time, the average compliance of all users is falling (%+.1f points between the first and last weeks)." % (b - a)) if b - a < -1 else
                   "Over time, the average compliance of all users has been steady.")
    sc = kpi["status_counts"]
    out.append(f"Right now {sc['active']} user(s) are active, {sc['at_risk']} are at risk of stopping, {sc['dormant']} are dormant and {sc['never']} never started.")
    return out


def build_user_report(user, tzname="UTC"):
    """Everything needed for the per-person Excel / PDF report."""
    d = user_detail(user, timeline_limit=0)
    s = d["summary"]
    pairs = [("Email", s["email"]), ("Joined", s["joined"]), ("Account age (days)", s["account_age_days"]),
             ("Status", s["status"].replace("_", " ")), ("Sessions", s["sessions"]), ("Active days", s["active_days"]),
             ("Total time worn", s["total_time"]), ("Average session", s["avg_session"]),
             ("Average compliance %", s["avg_compliance"] if s["avg_compliance"] is not None else "-"),
             ("Best / worst session %", f"{s['best_compliance']} / {s['worst_compliance']}" if s["sessions"] else "-"),
             ("Sessions with 60%+ compliance", f"{s['good_sessions_pct']}%" if s["good_sessions_pct"] is not None else "-"),
             ("Total alerts", s["total_alerts"]), ("Alerts per hour worn", s["alerts_per_hour"] if s["alerts_per_hour"] is not None else "-"),
             ("Average forward tilt (deg)", s["avg_deviation"] if s["avg_deviation"] is not None else "-"),
             ("Current / longest streak (days)", f"{s['streak_current']} / {s['streak_longest']}"),
             ("Longest break between active days", f"{s['longest_gap_days']} day(s)"),
             ("Alert angle / safe zone / sideways limit", f"{s['settings']['warning_angle']} / {s['settings']['safe_zone']} / {s['settings']['lateral_limit']} deg"),
             ("Height / weight", f"{user.height_cm} cm / {user.weight_kg} kg" if user.height_cm and user.weight_kg else "-"),
             ("BMI", f"{user.body['bmi']} ({user.body['category']})" if user.body else "-"),
             ("Times shown", tzname)]
    from . import analytics2
    sess = [{"date": timezone.localtime(x.end_time), "start": timezone.localtime(x.start_time), "end": timezone.localtime(x.end_time),
             "duration": x.duration_seconds, "score": x.compliance_score, "alerts": x.alert_count, "avg": x.avg_sagittal_deviation,
             "median": x.median_dev, "max": x.max_dev, "peak": x.peak_load, "mode": x.mode, "source": x.source, "angle": x.warning_angle,
             "trend": x.trend if (x.trend and len(x.trend.get("pitch") or []) >= 2) else None}
            for x in d["sessions"]]
    daily_rows = analytics2.daily(analytics2.load_sessions(user.id))
    return {"title": f"Posture report - {s['email']}", "subtitle": f"Generated {timezone.localtime().strftime('%Y-%m-%d %H:%M')} ({tzname})",
            "pairs": pairs, "insights": user_insights(s, d["weekly"]), "weekly": d["weekly"], "sessions": sess, "hours": d["hours"],
            "daily": daily_rows}


def build_platform_report(tzname="UTC", weeks=26):
    from .models import Review
    kpi = overview()
    weekly = weekly_platform_series(weeks)
    rows = user_rows(sort="sessions", direction="desc")
    pairs = [("Registered users", kpi["total_users"]), ("Users with at least one session", f"{kpi['users_with_sessions']} ({kpi['activation_rate']}%)"),
             ("Active today / 7 days / 30 days", f"{kpi['dau']} / {kpi['wau']} / {kpi['mau']}"),
             ("New users (7 / 30 days)", f"{kpi['new_users_7d']} / {kpi['new_users_30d']}"),
             ("Total sessions", kpi["total_sessions"]), ("Total hours worn", kpi["total_hours"]),
             ("Average session length", kpi["avg_session"]),
             ("Average compliance %", kpi["avg_compliance"] if kpi["avg_compliance"] is not None else "-"),
             ("Total slouch alerts", kpi["total_alerts"]), ("Average forward tilt (deg)", kpi["avg_deviation"] if kpi["avg_deviation"] is not None else "-"),
             ("Times shown", tzname)]
    users = [{**r, "created_at": timezone.localtime(r["created_at"]),
              "last_active": timezone.localtime(r["last_active"]) if r["last_active"] else None} for r in rows]
    reviews = [{"date": timezone.localtime(r.created_at).date().isoformat(), "rating": r.rating, "name": r.display_name or "-",
                "comment": r.comment, "shown": r.show_on_home} for r in Review.objects.all()]
    return {"title": "BioSpine - all-users report", "subtitle": f"Generated {timezone.localtime().strftime('%Y-%m-%d %H:%M')} ({tzname})",
            "pairs": pairs, "insights": platform_insights(kpi, weekly), "weekly": weekly, "daily": daily_series(60),
            "users": users, "distribution": compliance_distribution(), "reviews": reviews}
