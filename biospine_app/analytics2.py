"""
Staff analytics v5.1 - extra analysis for the tabbed /staff/analytics/ area.

Most functions here are PURE (they take plain lists / dicts), so they are easy to test without a database.
Only `load_sessions()` and the few `*_for_*` helpers at the bottom talk to Django.

A "session" dict looks like:
    {"uid": 3, "start": <aware datetime, local time>, "end": <...>, "dur": seconds,
     "comp": compliance %, "alerts": int, "dev": average forward-lean degrees}
(PostureSession.date is the moment the session was SAVED, so start = end - duration.)
"""
import datetime as dt
from collections import defaultdict

DAYPARTS = [("Early morning", "5-9", 5, 9), ("Morning", "9-12", 9, 12), ("Afternoon", "12-17", 12, 17),
            ("Evening", "17-22", 17, 22), ("Night", "22-5", 22, 29)]      # 29 = 5 the next day
GOOD = 60


def _r(v, nd=1):
    return None if v is None else round(v, nd)


def fmt_minutes(minutes):
    minutes = int(round(minutes or 0))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


# ----------------------------------------------------------------------------------------------
# splitting sessions across clock hours / days
# ----------------------------------------------------------------------------------------------
def _pieces(s):
    """Yield (date, weekday, hour, seconds) for every clock hour the session touched."""
    start, end = s["start"], s["end"]
    if s["dur"] <= 0:
        return
    cur = start
    guard = 0
    while cur < end and guard < 400:
        guard += 1
        nxt = min(end, (cur.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)))
        secs = (nxt - cur).total_seconds()
        if secs > 0:
            yield cur.date(), cur.weekday(), cur.hour, secs
        cur = nxt


def hourly(sessions):
    """24 rows: how long people were wearing it in each clock hour and how well they sat."""
    acc = [{"secs": 0.0, "wc": 0.0, "wd": 0.0, "al": 0.0, "n": 0} for _ in range(24)]
    for s in sessions:
        touched = set()
        for _d, _w, hr, secs in _pieces(s):
            a = acc[hr]
            a["secs"] += secs
            a["wc"] += (s["comp"] or 0) * secs
            a["wd"] += (s["dev"] or 0) * secs
            a["al"] += (s["alerts"] or 0) * secs / s["dur"]
            touched.add(hr)
        for hr in touched:
            acc[hr]["n"] += 1
    out = []
    for hr, a in enumerate(acc):
        sec = a["secs"]
        out.append({"hour": hr, "label": f"{hr:02d}:00", "minutes": _r(sec / 60), "sessions": a["n"],
                    "avg_dev": _r(a["wd"] / sec) if sec else None, "compliance": _r(a["wc"] / sec) if sec else None,
                    "alerts": _r(a["al"]), "alerts_per_hour": _r(a["al"] / (sec / 3600)) if sec >= 60 else None})
    return out


def dayparts(hour_rows):
    out = []
    for name, span, a, b in DAYPARTS:
        hrs = [hour_rows[h % 24] for h in range(a, b)]
        sec = sum((h["minutes"] or 0) for h in hrs) * 60
        wc = sum((h["compliance"] or 0) * (h["minutes"] or 0) for h in hrs)
        wd = sum((h["avg_dev"] or 0) * (h["minutes"] or 0) for h in hrs)
        mins = sec / 60
        out.append({"name": name, "span": span, "minutes": _r(mins), "sessions": sum(h["sessions"] for h in hrs),
                    "compliance": _r(wc / mins) if mins else None, "avg_dev": _r(wd / mins) if mins else None,
                    "alerts": _r(sum(h["alerts"] or 0 for h in hrs))})
    return out


def daily(sessions):
    """One row per calendar day: time worn, average deviation, compliance, alerts, first / last time."""
    days = {}
    for s in sessions:
        for d, _w, _h, secs in _pieces(s):
            a = days.setdefault(d, {"secs": 0.0, "wc": 0.0, "wd": 0.0, "al": 0.0, "ids": set()})
            a["secs"] += secs
            a["wc"] += (s["comp"] or 0) * secs
            a["wd"] += (s["dev"] or 0) * secs
            a["al"] += (s["alerts"] or 0) * secs / s["dur"]
            a["ids"].add(id(s))
    out = []
    for d in sorted(days):
        a = days[d]
        day_s = [s for s in sessions if id(s) in a["ids"]]
        out.append({"date": d.isoformat(), "weekday": d.strftime("%a"), "minutes": _r(a["secs"] / 60), "sessions": len(a["ids"]),
                    "avg_dev": _r(a["wd"] / a["secs"]) if a["secs"] else None,
                    "compliance": _r(a["wc"] / a["secs"]) if a["secs"] else None, "alerts": int(round(a["al"])),
                    "first": min(x["start"] for x in day_s).strftime("%H:%M"), "last": max(x["end"] for x in day_s).strftime("%H:%M"),
                    "periods": ", ".join(f"{x['start'].strftime('%H:%M')}-{x['end'].strftime('%H:%M')}" for x in sorted(day_s, key=lambda z: z["start"]))})
    return out


def weekday_stats(sessions):
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    acc = [{"secs": 0.0, "wc": 0.0, "wd": 0.0, "days": set(), "ids": set()} for _ in range(7)]
    for s in sessions:
        for d, wd, _h, secs in _pieces(s):
            a = acc[wd]
            a["secs"] += secs
            a["wc"] += (s["comp"] or 0) * secs
            a["wd"] += (s["dev"] or 0) * secs
            a["days"].add(d)
            a["ids"].add(id(s))
    return [{"day": names[i], "minutes": _r(a["secs"] / 60), "sessions": len(a["ids"]),
             "avg_minutes_per_day": _r(a["secs"] / 60 / len(a["days"])) if a["days"] else None,
             "compliance": _r(a["wc"] / a["secs"]) if a["secs"] else None,
             "avg_dev": _r(a["wd"] / a["secs"]) if a["secs"] else None} for i, a in enumerate(acc)]


def minutes_heatmap(sessions):
    """7 x 24 grid (Mon..Sun x hour) of minutes worn."""
    grid = [[0.0] * 24 for _ in range(7)]
    for s in sessions:
        for _d, wd, hr, secs in _pieces(s):
            grid[wd][hr] += secs / 60
    return [[int(round(v)) for v in row] for row in grid]


def weekly(sessions):
    """Per ISO week (Monday start): sessions, hours, compliance, deviation, alerts."""
    wk = {}
    for s in sessions:
        mon = (s["start"].date() - dt.timedelta(days=s["start"].weekday()))
        a = wk.setdefault(mon, {"n": 0, "secs": 0.0, "wc": 0.0, "wd": 0.0, "al": 0})
        a["n"] += 1
        a["secs"] += s["dur"]
        a["wc"] += (s["comp"] or 0) * s["dur"]
        a["wd"] += (s["dev"] or 0) * s["dur"]
        a["al"] += s["alerts"] or 0
    return [{"week": m.isoformat(), "sessions": a["n"], "hours": _r(a["secs"] / 3600, 2),
             "compliance": _r(a["wc"] / a["secs"]) if a["secs"] else None,
             "avg_dev": _r(a["wd"] / a["secs"]) if a["secs"] else None, "alerts": a["al"]} for m, a in sorted(wk.items())]


# ----------------------------------------------------------------------------------------------
# the report the user sees on their own "My report" card (plain language), for the admin
# ----------------------------------------------------------------------------------------------
def _score(sessions):
    t = sum(s["dur"] for s in sessions)
    return (sum((s["comp"] or 0) * s["dur"] for s in sessions) / t) if t else None


def plain_report(sessions, previous=None, days=None, streak=0):
    """Same ideas and wording as the client's "My report" (best day, best hour, trend ...)."""
    out = {"sessions": len(sessions), "seconds": sum(s["dur"] for s in sessions), "score": None, "delta": None,
           "alerts": sum(s["alerts"] or 0 for s in sessions), "alerts_per_hour": None, "best_day": None, "worst_day": None,
           "best_hour": None, "worst_hour": None, "avg_dev": None, "time_text": "0 min", "streak": streak, "sentences": []}
    out["time_text"] = fmt_minutes(out["seconds"] / 60)
    if not sessions:
        out["sentences"] = ["No sessions in this period."]
        return out
    sc = _score(sessions)
    out["score"] = _r(sc, 0)
    out["avg_dev"] = _r(sum((s["dev"] or 0) * s["dur"] for s in sessions) / out["seconds"]) if out["seconds"] else None
    out["alerts_per_hour"] = _r(out["alerts"] / (out["seconds"] / 3600)) if out["seconds"] else 0
    drows = [d for d in daily(sessions) if (d["minutes"] or 0) >= 5 and d["compliance"] is not None]
    if drows:
        out["best_day"] = max(drows, key=lambda d: d["compliance"])
        out["worst_day"] = min(drows, key=lambda d: d["compliance"])
    hrows = [h for h in hourly(sessions) if (h["minutes"] or 0) >= 5 and h["compliance"] is not None]
    if hrows:
        out["best_hour"] = max(hrows, key=lambda h: h["compliance"])
        out["worst_hour"] = min(hrows, key=lambda h: h["compliance"])
    if previous:
        ps, pt = _score(previous), sum(s["dur"] for s in previous)
        if ps is not None and pt >= 600 and out["seconds"] >= 600:
            out["delta"] = int(round(sc)) - int(round(ps))
    word = "excellent" if sc >= 80 else "good" if sc >= 60 else "a little low"
    ndays = len(drows) if drows else len({s["start"].date() for s in sessions})
    o = [f"Wore BioSpine for {fmt_minutes(out['seconds'] / 60)} over {ndays} day(s). Posture score {out['score']:.0f}%, which is {word}."]
    if out["delta"] is not None:
        o.append(f"{abs(out['delta'])} points {'better' if out['delta'] > 1 else 'lower'} than the previous {days} days." if abs(out["delta"]) > 1
                 else f"About the same as the previous {days} days.")
    if out["best_day"] and out["worst_day"] and out["best_day"]["date"] != out["worst_day"]["date"]:
        o.append(f"Best day {out['best_day']['date']} ({out['best_day']['compliance']:.0f}%). Toughest day {out['worst_day']['date']} ({out['worst_day']['compliance']:.0f}%).")
    if out["best_hour"] and out["worst_hour"] and out["best_hour"]["hour"] != out["worst_hour"]["hour"]:
        o.append(f"Sits best around {out['best_hour']['hour']}:00 and slouches most around {out['worst_hour']['hour']}:00.")
    o.append(f"Reminded {out['alerts']} time(s), about {out['alerts_per_hour']} per hour worn." + (f" Streak: {streak} day(s)." if streak else ""))
    out["sentences"] = o
    return out


# ----------------------------------------------------------------------------------------------
# platform-wide distributions and funnels
# ----------------------------------------------------------------------------------------------
def _bucketize(values, edges, labels):
    counts = [0] * len(labels)
    for v in values:
        for i in range(len(labels)):
            hi = edges[i + 1] if i + 1 < len(edges) else float("inf")
            if edges[i] <= v < hi:
                counts[i] += 1
                break
    return [{"label": l, "count": c} for l, c in zip(labels, counts)]


def deviation_distribution(sessions):
    return _bucketize([s["dev"] for s in sessions if s["dev"] is not None], [0, 3, 6, 10, 15],
                      ["under 3 deg (excellent)", "3-6 deg", "6-10 deg", "10-15 deg", "15 deg or more"])


def length_distribution(sessions):
    return _bucketize([s["dur"] / 60 for s in sessions], [0, 5, 15, 30, 60, 120],
                      ["under 5 min", "5-15 min", "15-30 min", "30-60 min", "1-2 hours", "over 2 hours"])


def quality_daily(sessions, days=60, today=None):
    """Daily platform averages: compliance and deviation (weighted by time worn) + active users."""
    today = today or (max((s["end"].date() for s in sessions), default=dt.date.today()))
    first = today - dt.timedelta(days=days - 1)
    acc = {}
    for s in sessions:
        for d, _w, _h, secs in _pieces(s):
            if d < first:
                continue
            a = acc.setdefault(d, {"secs": 0.0, "wc": 0.0, "wd": 0.0, "u": set()})
            a["secs"] += secs
            a["wc"] += (s["comp"] or 0) * secs
            a["wd"] += (s["dev"] or 0) * secs
            a["u"].add(s["uid"])
    out = []
    for i in range(days):
        d = first + dt.timedelta(days=i)
        a = acc.get(d)
        out.append({"date": d.isoformat(), "compliance": _r(a["wc"] / a["secs"]) if a and a["secs"] else None,
                    "avg_dev": _r(a["wd"] / a["secs"]) if a and a["secs"] else None,
                    "hours": _r(a["secs"] / 3600, 2) if a else 0, "users": len(a["u"]) if a else 0})
    return out


def trend_lists(sessions, n=8, min_sessions=6):
    """Who is getting better / worse: average compliance of the last 3 sessions minus the first 3."""
    by = defaultdict(list)
    for s in sessions:
        by[s["uid"]].append(s)
    rows = []
    for uid, lst in by.items():
        if len(lst) < min_sessions:
            continue
        lst.sort(key=lambda s: s["end"])
        first = sum(s["comp"] or 0 for s in lst[:3]) / 3
        last = sum(s["comp"] or 0 for s in lst[-3:]) / 3
        rows.append({"uid": uid, "sessions": len(lst), "first": _r(first), "last": _r(last), "change": _r(last - first)})
    rows.sort(key=lambda r: r["change"])
    return {"declining": [r for r in rows[:n] if r["change"] < -1], "improving": [r for r in rows[::-1][:n] if r["change"] > 1]}


def funnel(rows):
    """Registered -> email confirmed -> first session -> 5 sessions -> 20 sessions -> 7-day streak."""
    steps = [("Signed up", len(rows)),
             ("Confirmed email", sum(1 for r in rows if r.get("email_verified"))),
             ("Recorded a session", sum(1 for r in rows if r["sessions"] >= 1)),
             ("5+ sessions", sum(1 for r in rows if r["sessions"] >= 5)),
             ("20+ sessions", sum(1 for r in rows if r["sessions"] >= 20)),
             ("Reached a 7-day streak", sum(1 for r in rows if r["longest_streak"] >= 7))]
    top = steps[0][1] or 1
    return [{"label": l, "count": c, "pct": _r(100 * c / top)} for l, c in steps]


def sessions_per_user(rows):
    return _bucketize([r["sessions"] for r in rows], [0, 1, 2, 5, 10, 20, 50],
                      ["none", "1", "2-4", "5-9", "10-19", "20-49", "50 or more"])


def stickiness(daily_users, mau):
    """Average daily active users / monthly active users, in %."""
    if not mau or not daily_users:
        return None
    return _r(100 * (sum(daily_users) / len(daily_users)) / mau)


# ----------------------------------------------------------------------------------------------
# body / BMI
# ----------------------------------------------------------------------------------------------
BMI_BANDS = [("under", "Underweight (under 18.5)"), ("healthy", "Healthy weight (18.5-24.9)"),
             ("over", "Overweight (25-29.9)"), ("obese", "Obesity range (30+)")]


def body_stats(rows):
    have = [r for r in rows if r.get("bmi") is not None]
    out = {"total": len(rows), "with_body": len(have), "missing": len(rows) - len(have),
           "avg_height": _r(sum(r["height_cm"] for r in have) / len(have)) if have else None,
           "avg_weight": _r(sum(r["weight_kg"] for r in have) / len(have)) if have else None,
           "avg_bmi": _r(sum(r["bmi"] for r in have) / len(have)) if have else None, "bands": [], "hist": []}
    for key, label in BMI_BANDS:
        grp = [r for r in have if r["bmi_key"] == key]
        comps = [r["avg_compliance"] for r in grp if r["avg_compliance"] is not None]
        devs = [r["avg_deviation"] for r in grp if r["avg_deviation"] is not None]
        out["bands"].append({"key": key, "label": label, "users": len(grp),
                             "pct": _r(100 * len(grp) / len(have)) if have else 0,
                             "avg_compliance": _r(sum(comps) / len(comps)) if comps else None,
                             "avg_dev": _r(sum(devs) / len(devs)) if devs else None,
                             "avg_sessions": _r(sum(r["sessions"] for r in grp) / len(grp)) if grp else None,
                             "avg_hours": _r(sum(r["total_seconds"] for r in grp) / len(grp) / 3600, 1) if grp else None})
    out["hist"] = _bucketize([r["bmi"] for r in have], [0, 16, 18.5, 21, 23, 25, 27.5, 30, 35],
                             ["under 16", "16-18.4", "18.5-20.9", "21-22.9", "23-24.9", "25-27.4", "27.5-29.9", "30-34.9", "35+"])
    return out


# ----------------------------------------------------------------------------------------------
# Django glue (database access)
# ----------------------------------------------------------------------------------------------
def load_sessions(user_id=None, since=None):
    """All saved sessions as plain dicts with LOCAL start / end times (uses the active timezone)."""
    from django.utils import timezone
    from .models import PostureSession
    qs = PostureSession.objects.all()
    if user_id is not None:
        qs = qs.filter(user_id=user_id)
    if since is not None:
        qs = qs.filter(date__gte=since)
    out = []
    for sid, uid, date, started, ended, dur, comp, alerts, dev, source in qs.order_by("date").values_list(
            "id", "user_id", "date", "started_at", "ended_at", "duration_seconds", "compliance_score", "alert_count",
            "avg_sagittal_deviation", "source"):
        end = timezone.localtime(ended or date)
        dur = dur or 0
        start = timezone.localtime(started) if started else end - dt.timedelta(seconds=dur)
        out.append({"id": sid, "uid": uid, "start": start, "end": end, "dur": dur, "comp": comp or 0, "alerts": alerts or 0,
                    "dev": dev or 0, "source": source or "device"})
    return out


def profile_rows(q="", status="", sort="joined", direction="desc"):
    """analytics.user_rows() plus body data, e-mail confirmation and a mini compliance sparkline per user."""
    from . import analytics
    from .body import bmi_info
    from .models import PostureSession, UserProfile
    rows = analytics.user_rows(q=q, status=status, sort="joined" if sort in ("bmi", "deviation") else sort, direction=direction)
    extra = {u["id"]: u for u in UserProfile.objects.values("id", "height_cm", "weight_kg", "email_verified", "weekly_email", "daily_goal_minutes")}
    spark = defaultdict(list)
    for uid, comp in PostureSession.objects.order_by("date").values_list("user_id", "compliance_score"):
        spark[uid].append(comp or 0)
    for r in rows:
        e = extra.get(r["id"], {})
        info = bmi_info(e.get("height_cm"), e.get("weight_kg")) or {}
        r.update({"height_cm": e.get("height_cm"), "weight_kg": e.get("weight_kg"), "email_verified": e.get("email_verified", False),
                  "weekly_email": e.get("weekly_email", False), "bmi": info.get("bmi"), "bmi_key": info.get("key", ""),
                  "bmi_category": info.get("category", ""), "spark": spark.get(r["id"], [])[-12:],
                  "initial": (r["email"][:1] or "?").upper()})
    if sort == "bmi":
        rows.sort(key=lambda r: (r["bmi"] is None, r["bmi"] or 0), reverse=(direction != "asc"))
    elif sort == "deviation":
        rows.sort(key=lambda r: (r["avg_deviation"] is None, r["avg_deviation"] or 0), reverse=(direction != "asc"))
    return rows


def spark_points(values, w=96, h=26):
    """SVG polyline points for a tiny compliance chart (values 0..100)."""
    if len(values) < 2:
        return ""
    step = w / (len(values) - 1)
    return " ".join(f"{i * step:.1f},{h - (max(0, min(100, v)) / 100) * (h - 3) - 1.5:.1f}" for i, v in enumerate(values))


def user_profile_context(user, days=30):
    """Everything on one person's profile page, i.e. what that person sees on their own screens + more."""
    from django.utils import timezone
    from . import analytics
    base = analytics.user_detail(user, timeline_limit=80)
    sessions = load_sessions(user.id)
    now = timezone.localtime()
    window = [s for s in sessions if days == 0 or s["end"] >= now - dt.timedelta(days=days)]
    prev = [s for s in sessions if days and now - dt.timedelta(days=2 * days) <= s["end"] < now - dt.timedelta(days=days)]
    hrs = hourly(sessions)
    rep = plain_report(window, prev, days or None, user.current_streak)
    srows = [{"start": s["start"].strftime("%Y-%m-%d %H:%M"), "end": s["end"].strftime("%H:%M"), "minutes": _r(s["dur"] / 60),
              "compliance": s["comp"], "alerts": s["alerts"], "avg_dev": _r(s["dev"]),
              "dev_class": "good" if (s["dev"] or 0) < 6 else "warn" if (s["dev"] or 0) < 12 else "bad"} for s in reversed(sessions)]
    cards = [session_row(x) for x in user.sessions.all()[:15]]
    tot_s = sum(x["dur"] for x in window)
    overall = good_bad_donut(tot_s, (sum(x["comp"] * x["dur"] for x in window) / tot_s) if tot_s else 0) if tot_s else None
    return {"base": base, "report": rep, "cards": cards, "overall_donut": overall, "daily": daily(sessions), "hourly": hrs, "dayparts": dayparts(hrs),
            "weekdays": weekday_stats(sessions), "weekly": weekly(sessions), "session_rows": srows,
            "heatmap": minutes_heatmap(sessions), "body": user.body, "days": days}


def platform_context(tzname, history_days=60):
    """Shared numbers for the Time / Posture / Engagement / Body tabs."""
    from django.utils import timezone
    sessions = load_sessions()
    hrs = hourly(sessions)
    return {"sessions": sessions, "hourly": hrs, "dayparts": dayparts(hrs), "weekdays": weekday_stats(sessions),
            "heatmap": minutes_heatmap(sessions), "dev_dist": deviation_distribution(sessions),
            "len_dist": length_distribution(sessions), "quality": quality_daily(sessions, history_days),
            "trends": trend_lists(sessions)}


# ----------------------------------------------------------------------------------------------
# per-session graphs (drawn on the staff pages as plain SVG, so they work without any chart library)
# ----------------------------------------------------------------------------------------------
def trend_chart(trend, threshold=None, start=None, width=640, height=170):
    """Everything an SVG needs to draw "lean angle over time" for one session. Returns None when there is no graph data."""
    if not trend or not isinstance(trend, dict) or len(trend.get("pitch") or []) < 2:
        return None
    pitch, roll, bad = trend["pitch"], trend.get("roll") or [], trend.get("bad") or []
    step = float(trend.get("step") or 1)
    n = len(pitch)
    mx = max([abs(v) for v in pitch] + [abs(v) for v in roll] + [float(threshold or 0) * 1.2, 20])
    top = min(90, max(20, int(-(-mx // 10) * 10)))            # round the vertical range up to a multiple of 10
    L, R, T, B = 38, 10, 10, 26
    pw, ph = width - L - R, height - T - B
    X = lambda i: L + pw * i / (n - 1)
    Y = lambda v: T + ph * (1 - (v + top) / (2 * top))        # -top .. +top  ->  bottom .. top
    seconds = step * (n - 1)
    pts = lambda arr: " ".join(f"{X(i):.1f},{Y(max(-top, min(top, v))):.1f}" for i, v in enumerate(arr[:n]))
    bands, run = [], None
    for i, b in enumerate(bad[:n]):
        if b >= 0.5 and run is None:
            run = i
        if (b < 0.5 or i == n - 1) and run is not None:
            end_i = i if b < 0.5 else i
            bands.append({"x": round(X(run), 1), "w": round(max(2.0, X(end_i) - X(run)), 1)})
            run = None
    ticks = []
    for k in range(5):
        frac = k / 4
        label = (start + dt.timedelta(seconds=seconds * frac)).strftime("%H:%M") if start else f"{seconds * frac / 60:.0f} min"
        ticks.append({"x": round(L + pw * frac, 1), "label": label})
    yticks = [{"y": round(Y(v), 1), "label": f"{v:+d}" if v else "0"} for v in (-top, -top // 2, 0, top // 2, top)]
    thr = None
    if threshold:
        thr = {"y_pos": round(Y(threshold), 1), "y_neg": round(Y(-threshold), 1), "label": f"alert angle {threshold:g} deg"}
    return {"band_y": T, "band_h": round(ph, 1), "w": width, "h": height, "L": L, "R": width - R, "T": T, "B": height - B, "pitch": pts(pitch), "roll": pts(roll) if roll else "",
            "bands": bands, "ticks": ticks, "yticks": yticks, "zero_y": round(Y(0), 1), "thr": thr,
            "minutes": round(seconds / 60, 1), "points": n, "top": top}


GOOD_C, BAD_C = "#34d399", "#f87171"
STRAIN_COLORS = {"forward": "#f87171", "backward": "#fbbf24", "left": "#38bdf8", "right": "#a78bfa"}
STRAIN_NAMES = {"forward": "Forward slouch", "backward": "Leaning back", "left": "Leaning left", "right": "Leaning right"}


def donut(parts, center=""):
    """Circle diagram as SVG circles. parts = [(label, value, colour)]. Returns None when there is nothing to show."""
    total = sum(v for _l, v, _c in parts)
    if total <= 0:
        return None
    r = 38.0
    c = 6.2832 * r
    acc, segs = 0.0, []
    for label, v, colour in parts:
        if v <= 0:
            continue
        frac = v / total
        segs.append({"color": colour, "label": label, "pct": round(100 * frac, 1), "value": round(v, 1),
                     "dash": f"{c * frac:.2f} {c - c * frac:.2f}", "offset": f"{-acc * c:.2f}"})
        acc += frac
    return {"r": r, "segs": segs, "center": center, "total": round(total, 1)}


def good_bad_donut(duration_seconds, score):
    good = duration_seconds * score / 100.0 / 60.0
    bad = duration_seconds / 60.0 - good
    return donut([("Good posture (min)", good, GOOD_C), ("Slouching (min)", bad, BAD_C)], f"{score:.0f}%")


def strain_donut(strain):
    return donut([(STRAIN_NAMES[k], strain.get(k, 0) / 60.0, STRAIN_COLORS[k]) for k in ("forward", "backward", "left", "right")]) if strain else None


def session_row(s, tzname_unused=None):
    """One session as a dict for templates / reports (s is a PostureSession model instance)."""
    from django.utils import timezone
    start, end = timezone.localtime(s.start_time), timezone.localtime(s.end_time)
    chart = trend_chart(s.trend, s.warning_angle, start)
    strain = s.strain or {}
    total_strain = sum(strain.values()) or 0
    return {
        "id": s.id, "start": start, "end": end, "day": start.strftime("%a %d %b %Y"), "range": f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}",
        "minutes": _r(s.duration_seconds / 60), "score": s.compliance_score, "alerts": s.alert_count, "avg": _r(s.avg_sagittal_deviation),
        "median": _r(s.median_dev), "max": _r(s.max_dev), "avg_roll": _r(s.avg_roll), "max_roll": _r(s.max_roll), "peak_load": s.peak_load,
        "mode": s.mode or "-", "source": s.source or "device", "angle": s.warning_angle, "chart": chart,
        "strain": [{"name": k, "sec": v, "pct": _r(100 * v / total_strain) if total_strain else 0} for k, v in strain.items() if v],
        "events": [{"time": dt.datetime.fromtimestamp(e["t"] / 1000, start.tzinfo).strftime("%H:%M:%S") if e.get("t") else "", "type": e.get("type", ""),
                    "title": e.get("title", ""), "detail": e.get("detail", "")} for e in (s.events or [])],
        "has_graph": chart is not None, "donut": good_bad_donut(s.duration_seconds, s.compliance_score), "strain_donut": strain_donut(s.strain),
        "dev_class": "good" if (s.avg_sagittal_deviation or 0) < 6 else "warn" if (s.avg_sagittal_deviation or 0) < 12 else "bad",
    }
