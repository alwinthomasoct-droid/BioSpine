"""
Rewards helpers (pure Python): XP from a session, and a safe merge for the per-account "extras"
(back breaks, quiz best, quests, badges) so progress follows the account to every device.
"""
import json

MAX_EXTRAS_BYTES = 24000


def session_xp(duration_seconds, score):
    """Same formula as the website: 2 XP per minute x score, +10 / +25 bonus for good sessions."""
    duration_seconds = max(0, int(duration_seconds or 0))
    score = max(0, min(100, int(score or 0)))
    base = int((duration_seconds / 60.0) * 2 * (score / 100.0) + 0.5)       # JS Math.round (halves go up)
    bonus = 25 if duration_seconds >= 600 and score >= 90 else 10 if duration_seconds >= 300 and score >= 75 else 0
    return base + bonus


def _num(v, hi=10**6):
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        return 0
    return max(0, min(hi, x))


def sanitize_extras(raw):
    """Keep only the keys we know, with safe types and sizes."""
    raw = raw if isinstance(raw, dict) else {}
    day = lambda k: isinstance(k, str) and len(k) == 10 and k[4] == "-" and k[7] == "-"
    out = {
        "breaks": _num(raw.get("breaks")), "breakXp": _num(raw.get("breakXp")), "quizBest": min(5, _num(raw.get("quizBest"), 5)),
        "lastLevel": _num(raw.get("lastLevel"), 1000),
        "breakDays": {k: _num(v, 1000) for k, v in list((raw.get("breakDays") or {}).items())[-400:] if day(k)} if isinstance(raw.get("breakDays"), dict) else {},
        "quizDays": {k: True for k, v in list((raw.get("quizDays") or {}).items())[-400:] if day(k) and v} if isinstance(raw.get("quizDays"), dict) else {},
        "quests": {k: sorted({str(i)[:20] for i in v if isinstance(i, str)})[:10] for k, v in list((raw.get("quests") or {}).items())[-400:]
                   if day(k) and isinstance(v, list)} if isinstance(raw.get("quests"), dict) else {},
        "earned": {str(k)[:20]: str(v)[:10] for k, v in list((raw.get("earned") or {}).items())[:60]} if isinstance(raw.get("earned"), dict) else {},
    }
    return out


def merge_extras(old, new):
    """Never lose progress: counters take the larger value, days and badges are combined."""
    a, b = sanitize_extras(old), sanitize_extras(new)
    out = {k: max(a[k], b[k]) for k in ("breaks", "breakXp", "quizBest", "lastLevel")}
    out["breakDays"] = {k: max(a["breakDays"].get(k, 0), b["breakDays"].get(k, 0)) for k in set(a["breakDays"]) | set(b["breakDays"])}
    out["quizDays"] = {k: True for k in set(a["quizDays"]) | set(b["quizDays"])}
    out["quests"] = {k: sorted(set(a["quests"].get(k, [])) | set(b["quests"].get(k, []))) for k in set(a["quests"]) | set(b["quests"])}
    out["earned"] = dict(b["earned"])
    for k, v in a["earned"].items():                     # keep the earliest date a badge was earned
        out["earned"][k] = min(v, out["earned"][k]) if k in out["earned"] else v
    # keep the stored size bounded: drop the oldest days first
    while len(json.dumps(out)) > MAX_EXTRAS_BYTES:
        for key in ("breakDays", "quizDays", "quests"):
            if out[key]:
                del out[key][sorted(out[key])[0]]
        if not any(out[k] for k in ("breakDays", "quizDays", "quests")):
            break
    return out
