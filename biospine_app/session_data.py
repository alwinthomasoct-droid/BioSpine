"""
Cleans the session details a browser sends to the server (pure Python, no Django).
Everything coming from a browser is untrusted: numbers are clamped, lists are shortened, text is trimmed.
"""
import datetime as dt

MAX_POINTS = 120
MAX_EVENTS = 40


def _f(v, lo, hi, default=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def _series(values, lo, hi, nd=1):
    out = []
    for v in (values if isinstance(values, list) else [])[:2000]:
        x = _f(v, lo, hi, 0.0)
        out.append(round(x, nd))
    return out


def _shrink(values, factor, avg=True):
    if factor <= 1:
        return values
    out = []
    for i in range(0, len(values), factor):
        chunk = values[i:i + factor]
        out.append(round(sum(chunk) / len(chunk), 2))
    return out


def clean_trend(trend):
    """-> {"step": seconds per point, "pitch": [...], "roll": [...], "bad": [0..1 ...]} with at most MAX_POINTS points, or None."""
    if not isinstance(trend, dict):
        return None
    step = _f(trend.get("step"), 1, 3600, 1.0)
    pitch = _series(trend.get("pitch"), -90, 90)
    roll = _series(trend.get("roll"), -90, 90)
    bad = _series(trend.get("bad"), 0, 1, 2)
    n = min(len(pitch), len(roll) or len(pitch), len(bad) or len(pitch))
    if n < 2:
        return None
    pitch, roll, bad = pitch[:n], (roll[:n] if roll else [0.0] * n), (bad[:n] if bad else [0.0] * n)
    factor = -(-n // MAX_POINTS)                      # ceiling division
    return {"step": round(step * factor, 2), "pitch": _shrink(pitch, factor), "roll": _shrink(roll, factor), "bad": _shrink(bad, factor)}


def clean_events(events):
    out = []
    for e in (events if isinstance(events, list) else [])[-MAX_EVENTS:]:
        if not isinstance(e, dict):
            continue
        out.append({"t": int(_f(e.get("t"), 0, 4e12, 0)), "type": str(e.get("type", ""))[:8],
                    "title": str(e.get("title", ""))[:60], "detail": str(e.get("detail", ""))[:120]})
    return out


def clean_strain(strain):
    if not isinstance(strain, dict):
        return None
    return {k: round(_f(strain.get(k), 0, 86400, 0.0), 1) for k in ("forward", "backward", "left", "right")}


def ms_to_dt(ms, now=None):
    """Browser epoch milliseconds -> aware UTC datetime, or None when it is not believable."""
    now = now or dt.datetime.now(dt.timezone.utc)
    x = _f(ms, 0, 4e12, None)
    if not x:
        return None
    t = dt.datetime.fromtimestamp(x / 1000.0, dt.timezone.utc)
    if t < dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) or t > now + dt.timedelta(days=1):
        return None
    return t


def clean_session(sess, now=None):
    """Returns the fields to store for one session, or None when it is too short / invalid."""
    if not isinstance(sess, dict):
        return None
    duration = int(_f(sess.get("duration"), 0, 86400, 0))
    if duration < 5:
        return None
    started, ended = ms_to_dt(sess.get("start"), now), ms_to_dt(sess.get("end"), now)
    if started and ended and ended < started:
        started = ended = None
    return {
        "duration_seconds": duration,
        "compliance_score": int(_f(sess.get("score"), 0, 100, 0)),
        "alert_count": int(_f(sess.get("alerts"), 0, 100000, 0)),
        "avg_sagittal_deviation": _f(sess.get("avg"), 0, 90, 0.0),
        "client_id": str(sess.get("id", ""))[:40] if str(sess.get("id", "")).replace("-", "").isalnum() else "",
        "started_at": started, "ended_at": ended,
        "source": "demo" if sess.get("source") == "demo" else "device",
        "mode": sess.get("mode") if sess.get("mode") in ("focus", "meeting", "rehab") else "",
        "warning_angle": _f(sess.get("angle"), 1, 90, None),
        "median_dev": _f(sess.get("median"), 0, 90, None), "max_dev": _f(sess.get("max"), 0, 90, None),
        "avg_roll": _f(sess.get("avgRoll"), 0, 90, None), "max_roll": _f(sess.get("maxRoll"), 0, 90, None),
        "peak_load": int(_f(sess.get("peakLoad"), 0, 200, 0)) if sess.get("peakLoad") is not None else None,
        "strain": clean_strain(sess.get("strain")), "trend": clean_trend(sess.get("trend")),
        "events": clean_events(sess.get("events")),
    }
