import datetime
import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import ai, emails
from .auth_utils import (client_ip, issue_token, json_error, read_json, throttle, token_required, too_many)
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone

from . import body as bodymod, rewards as rewardsmod, session_data
from .models import ChatMessage, PostureSession, Review, UserProfile

log = logging.getLogger(__name__)

# NOTE on csrf_exempt: these endpoints are authenticated with an `Authorization: Bearer` header that
# JavaScript adds by hand. Browsers never attach that header automatically, so cross-site request
# forgery (the attack CSRF protection exists for) is not possible against them.


def index(request):
    return render(request, "index.html")


REVIEW_AFTER_SESSIONS = 5   # the client is asked for a review once, after this many saved sessions


def _ai_off_response():
    return json_error("The AI assistant is switched off on this website.", 404, code="ai_off")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _clamp(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _body_payload(user):
    info = user.body
    return {"heightCm": user.height_cm, "weightKg": user.weight_kg, "info": info}


def _session_xp_total(user):
    return sum(rewardsmod.session_xp(d, s) for d, s in user.sessions.values_list("duration_seconds", "compliance_score"))


def _badge_stats(user):
    """Account-wide numbers (not just the newest 30 sessions) so badges and levels are the same on every device."""
    rows = list(user.sessions.values_list("duration_seconds", "compliance_score"))
    return {"sessions": len(rows), "totalSec": sum(d for d, _ in rows),
            "bestScore": max([s for d, s in rows if d >= 300], default=0),
            "perfect": any(d >= 300 and s >= 99 for d, s in rows)}


def _user_payload(user, token=None):
    total = user.sessions.count()
    my_review = Review.objects.filter(user=user).first()
    has_review = my_review is not None
    sessions = [
        {"date": s.date.isoformat(), "duration": s.duration_seconds, "score": s.compliance_score,
         "alerts": s.alert_count, "avg": s.avg_sagittal_deviation}
        for s in user.sessions.all()[:30]
    ]
    payload = {
        "email": user.email,
        "emailVerified": user.email_verified,
        "settings": {"angle": user.warning_angle, "safeZone": user.safe_zone,
                     "lateralLimit": user.lateral_limit, "mode": user.active_mode,
                     "dailyGoal": user.daily_goal_minutes, "weeklyEmail": user.weekly_email},
        "streak": {"current": user.current_streak, "longest": user.longest_streak},
        "sessions": sessions,
        "totalSessions": total,
        "sessionXp": _session_xp_total(user), "stats": _badge_stats(user),
        "extras": rewardsmod.sanitize_extras(user.extras),
        "body": _body_payload(user),
        # one-time review prompt: due after the 5th saved session, only if the person has not answered / dismissed it yet
        "review": {"promptDue": bool(total >= REVIEW_AFTER_SESSIONS and not user.review_prompt_done and not has_review),
                   "submitted": has_review,
                   "mine": ({"rating": my_review.rating, "comment": my_review.comment, "name": my_review.display_name} if my_review else None)},
    }
    if token:
        payload["token"] = token
    return payload


def _check_password(password, user=None):
    try:
        validate_password(password, user)
    except ValidationError as err:
        return " ".join(err.messages)
    return None


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
@csrf_exempt
@require_http_methods(["POST"])
def api_register(request):
    data, err = read_json(request)
    if err:
        return err
    ip = client_ip(request)
    if not throttle(f"register:{ip}", 8, 3600):
        return too_many("Too many sign-ups from this network. Please try again later.")

    email = str(data.get("email", "")).lower().strip()
    password = str(data.get("password", ""))
    try:
        validate_email(email)
    except ValidationError:
        return json_error("A valid email is required.", 400)
    problem = _check_password(password)
    if problem:
        return json_error(problem, 400)
    if UserProfile.objects.filter(email=email).exists():
        return json_error("An account with that email already exists. Please sign in instead.", 409, code="exists")

    height, weight, body_err = bodymod.clean_body(data.get("heightCm"), data.get("weightKg"))
    if body_err:
        return json_error(body_err, 400)
    user = UserProfile(email=email, height_cm=height, weight_kg=weight)
    if height:
        user.body_updated_at = timezone.now()
    user.set_password(password)
    user.save()
    email_sent = emails.send_verification(user)
    token = issue_token(user, request)
    return JsonResponse({"success": True, "emailSent": bool(email_sent and settings.EMAIL_CONFIGURED), "user": _user_payload(user, token)})


@csrf_exempt
@require_http_methods(["POST"])
def api_login(request):
    data, err = read_json(request)
    if err:
        return err
    email = str(data.get("email", "")).lower().strip()
    password = str(data.get("password", ""))
    ip = client_ip(request)
    # brute-force protection: per network and per target account
    if not throttle(f"login-ip:{ip}", 30, 900) or not throttle(f"login-email:{email}", 10, 900):
        return too_many("Too many sign-in attempts. Please wait 15 minutes and try again.")

    user = UserProfile.objects.filter(email=email).first()
    if user and not user.password_hash:
        return json_error("This account has no password yet. Use 'Forgot password?' to set one.", 401, code="needs_reset")
    if not user or not user.check_password(password):
        return json_error("Incorrect email or password.", 401, code="bad_credentials")

    token = issue_token(user, request)
    return JsonResponse({"success": True, "user": _user_payload(user, token)})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_session(request):
    """Silently restore a sign-in after a page reload."""
    return JsonResponse({"success": True, "user": _user_payload(request.bs_user)})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_logout(request):
    request.bs_token.delete()           # really signs this device out on the server
    return JsonResponse({"success": True})


@csrf_exempt
@require_http_methods(["POST"])
def api_forgot(request):
    data, err = read_json(request)
    if err:
        return err
    email = str(data.get("email", "")).lower().strip()
    if not throttle(f"forgot-ip:{client_ip(request)}", 10, 3600) or not throttle(f"forgot-email:{email}", 3, 3600):
        return too_many()
    user = UserProfile.objects.filter(email=email).first()
    if user:
        emails.send_password_reset(user)
    # same answer whether or not the account exists, so nobody can probe which emails are registered
    return JsonResponse({"success": True, "message": "If that email has an account, a reset link is on its way."})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_resend_verification(request):
    user = request.bs_user
    if user.email_verified:
        return JsonResponse({"success": True, "message": "Your email is already verified."})
    if not throttle(f"verify:{user.pk}", 3, 3600):
        return too_many()
    if not settings.EMAIL_CONFIGURED:
        return json_error("This website's email sending is not switched on yet, so no email could be sent. "
                          "Please tell the website owner.", 503, code="email_not_configured")
    if not emails.send_verification(user):
        return json_error("We could not send the email right now. Please try again in a few minutes "
                          "(if this keeps happening, the website's email settings need attention).", 503, code="email_failed")
    return JsonResponse({"success": True, "message": "Verification email sent. Please check your inbox (and the spam folder)."})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_change_password(request):
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    if not throttle(f"chpw:{user.pk}", 10, 3600):
        return too_many()
    if not user.check_password(str(data.get("current", ""))):
        return json_error("Your current password is incorrect.", 403)
    new = str(data.get("new", ""))
    problem = _check_password(new, user)
    if problem:
        return json_error(problem, 400)
    user.set_password(new)
    user.save(update_fields=["password_hash"])
    user.tokens.exclude(pk=request.bs_token.pk).delete()      # sign out every other device
    return JsonResponse({"success": True})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_delete_account(request):
    """Permanently deletes the account and ALL its data (sessions, chats, tokens)."""
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    if not throttle(f"delete:{user.pk}", 5, 3600):
        return too_many()
    if not user.check_password(str(data.get("password", ""))):
        return json_error("Password is incorrect.", 403)
    user.delete()
    return JsonResponse({"success": True})


@require_http_methods(["GET"])
@token_required
def api_export(request):
    """Download everything we store about the signed-in user (data portability)."""
    user = request.bs_user
    resp = JsonResponse({
        "body": {"heightCm": user.height_cm, "weightKg": user.weight_kg, "bmi": (user.body or {}).get("bmi")},
        "account": {"email": user.email, "created": user.created_at.isoformat(), "emailVerified": user.email_verified,
                    "weeklyEmail": user.weekly_email, "dailyGoalMinutes": user.daily_goal_minutes},
        "settings": {"warningAngle": user.warning_angle, "safeZone": user.safe_zone,
                     "lateralLimit": user.lateral_limit, "mode": user.active_mode},
        "streak": {"current": user.current_streak, "longest": user.longest_streak},
        "sessions": [{"date": s.date.isoformat(), "durationSeconds": s.duration_seconds, "complianceScore": s.compliance_score,
                      "alerts": s.alert_count, "avgSagittalDeviation": s.avg_sagittal_deviation,
                      "start": s.start_time.isoformat(), "end": s.end_time.isoformat(), "mode": s.mode, "source": s.source,
                      "medianLean": s.median_dev, "maxLean": s.max_dev, "peakNeckLoadLbs": s.peak_load, "strain": s.strain, "graph": s.trend}
                     for s in user.sessions.all()],
        "progress": rewardsmod.sanitize_extras(user.extras),
        "aiChats": [{"date": c.created_at.isoformat(), "question": c.question, "answer": c.answer, "context": c.context}
                    for c in user.chat_messages.all()],
        "review": ({"rating": user.review.rating, "comment": user.review.comment, "date": user.review.created_at.isoformat()}
                   if Review.objects.filter(user=user).exists() else None),
    }, json_dumps_params={"indent": 2})
    resp["Content-Disposition"] = 'attachment; filename="biospine_my_data.json"'
    return resp


# ---------------------------------------------------------------------------
# SESSIONS & SETTINGS SYNC
# ---------------------------------------------------------------------------
def _local_today(tz_offset_minutes):
    """Today's date for the USER (not the server) so streaks roll over at the user's midnight."""
    off = int(_clamp(tz_offset_minutes, -14 * 60, 14 * 60, 0))
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=off)).date()


def _credit_streak(user, compliance_score, today, min_compliance=60):
    """Day streak: the first session with compliance >= 60% on a calendar day extends the streak;
    missing a whole day resets it."""
    if compliance_score < min_compliance:
        return
    last = user.last_streak_date
    if last == today:
        return
    if last == today - datetime.timedelta(days=1):
        user.current_streak += 1
    else:
        user.current_streak = 1
    user.last_streak_date = today
    user.longest_streak = max(user.longest_streak, user.current_streak)
    user.save()


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_sync_user(request):
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    if not throttle(f"sync:{user.pk}", 240, 3600):
        return too_many("Syncing too fast. Please slow down.")

    s = data.get("settings")
    if isinstance(s, dict):
        user.warning_angle = _clamp(s.get("angle"), 5, 60, user.warning_angle)
        user.safe_zone = _clamp(s.get("safeZone"), 0.5, 15, user.safe_zone)
        user.lateral_limit = _clamp(s.get("lateralLimit"), 3, 40, user.lateral_limit)
        if s.get("mode") in ("focus", "meeting", "rehab"):
            user.active_mode = s["mode"]
        if "dailyGoal" in s:
            user.daily_goal_minutes = int(_clamp(s.get("dailyGoal"), 10, 960, user.daily_goal_minutes))
        if "weeklyEmail" in s:
            user.weekly_email = bool(s.get("weeklyEmail"))
        user.save()

    duplicate = False
    fields = session_data.clean_session(data.get("session"))
    if fields:
        cid = fields["client_id"]
        if cid and PostureSession.objects.filter(user=user, client_id=cid).exists():
            duplicate = True                                    # the browser re-sent a session we already have: do nothing twice
        else:
            try:
                obj = PostureSession.objects.create(user=user, **fields)
            except IntegrityError:
                obj, duplicate = None, True
            if obj is not None:
                if fields["ended_at"]:                          # keep the REAL end time (a late upload must not look like "now")
                    PostureSession.objects.filter(pk=obj.pk).update(date=fields["ended_at"])
                recent = (not fields["ended_at"]) or (timezone.now() - fields["ended_at"]) < timedelta(hours=36)
                if recent:
                    _credit_streak(user, fields["compliance_score"], _local_today(data.get("tzOffset", 0)))

    user.refresh_from_db()
    total = user.sessions.count()
    prompt_due = bool(total >= REVIEW_AFTER_SESSIONS and not user.review_prompt_done and not Review.objects.filter(user=user).exists())
    return JsonResponse({"success": True, "streak": {"current": user.current_streak, "longest": user.longest_streak},
                         "reviewPromptDue": prompt_due, "duplicate": duplicate, "totalSessions": total,
                         "sessionXp": _session_xp_total(user), "stats": _badge_stats(user)})


@require_http_methods(["GET"])
@token_required
def api_sessions(request):
    """Paged session history: /api/user/sessions?offset=30&limit=50"""
    offset = int(_clamp(request.GET.get("offset"), 0, 10**7, 0))
    limit = int(_clamp(request.GET.get("limit"), 1, 100, 50))
    qs = request.bs_user.sessions.all()
    total = qs.count()
    rows = [{"date": s.date.isoformat(), "duration": s.duration_seconds, "score": s.compliance_score,
             "alerts": s.alert_count, "avg": s.avg_sagittal_deviation} for s in qs[offset:offset + limit]]
    return JsonResponse({"success": True, "sessions": rows, "total": total, "nextOffset": offset + len(rows),
                         "hasMore": offset + len(rows) < total})


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
def _ai_gate(request, kind, per_hour, per_day):
    if not settings.AI_ENABLED:
        return _ai_off_response()
    user = request.bs_user
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
        return json_error("Please confirm your email address (check your inbox) to use the AI features.", 403, code="verify")
    if not throttle(f"{kind}-h:{user.pk}", per_hour, 3600):
        return too_many("You've reached the hourly AI limit. Please try again a little later.")
    if not throttle(f"{kind}-d:{user.pk}", per_day, 86400):
        return too_many("You've reached today's AI limit. It resets tomorrow.")
    return None


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_ai_diagnose(request):
    data, err = read_json(request)
    if err:
        return err
    blocked = _ai_gate(request, "diagnose", settings.AI_DIAGNOSE_PER_HOUR, settings.AI_DIAGNOSE_PER_DAY)
    if blocked:
        return blocked
    try:
        html_out, model = ai.diagnose_html(data)
    except ai.AIError as e:
        log.warning("diagnose failed: %s", e.detail or e.user_message)
        return json_error(e.user_message, 503, code=e.kind)
    return JsonResponse({"success": True, "html": html_out, "model": model})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_ai_chat(request):
    data, err = read_json(request)
    if err:
        return err
    query = str(data.get("query", "")).strip()[:500]
    if not query:
        return json_error("Type a question first.", 400)
    blocked = _ai_gate(request, "chat", settings.AI_CHAT_PER_HOUR, settings.AI_CHAT_PER_DAY)
    if blocked:
        return blocked

    live_dev, ptype, comp = data.get("liveDev"), data.get("livePostureType"), data.get("compliance")
    try:
        reply, model = ai.chat_reply(query, live_dev, ptype, comp)
    except ai.AIError as e:
        log.warning("chat failed: %s", e.detail or e.user_message)
        # Not saved to the chat history: it is not an AI answer. The visitor is told honestly and gets a labelled tip.
        return json_error(e.user_message, 503, code=e.kind, tip=ai.offline_tip(ptype, live_dev))

    msg = ChatMessage.objects.create(
        user=request.bs_user, question=query, answer=reply,
        context={"liveDev": str(live_dev)[:12], "livePostureType": str(ptype)[:40], "compliance": str(comp)[:12]})
    return JsonResponse({"success": True, "reply": reply, "chatId": msg.id, "model": model})


@require_http_methods(["GET"])
@token_required
def api_chat_history(request):
    history = [{"id": m.id, "question": m.question, "answer": m.answer, "date": m.created_at.isoformat(), "context": m.context}
               for m in request.bs_user.chat_messages.all()[:200]]
    return JsonResponse({"success": True, "history": history})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_chat_delete(request, chat_id):
    deleted, _ = ChatMessage.objects.filter(id=chat_id, user=request.bs_user).delete()
    if not deleted:
        return json_error("Not found", 404)
    return JsonResponse({"success": True})


# ---------------------------------------------------------------------------
# REVIEWS  (client side: one-time prompt after the 5th session; home page shows only admin-approved ones)
# ---------------------------------------------------------------------------
def _clean_line(value, limit):
    return " ".join(str(value or "").split())[:limit]


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_review(request):
    """Create or update the signed-in user's review (one per person)."""
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    if not throttle(f"review:{user.pk}", 10, 3600):
        return too_many()
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return json_error("Please choose a star rating from 1 to 5.", 400)
    if not 1 <= rating <= 5:
        return json_error("Please choose a star rating from 1 to 5.", 400)
    comment = str(data.get("comment") or "").strip()[:600]
    name = _clean_line(data.get("name"), 40) or "A BioSpine user"
    review, created = Review.objects.get_or_create(user=user, defaults={"rating": rating, "comment": comment, "display_name": name})
    if not created:
        review.rating, review.comment, review.display_name = rating, comment, name
        review.show_on_home = False         # an edited review goes back to the admin for approval
        review.save()
    if not user.review_prompt_done:
        user.review_prompt_done = True
        user.save(update_fields=["review_prompt_done"])
    return JsonResponse({"success": True, "message": "Thank you! Your review helps us improve."})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_review_dismiss(request):
    """'Maybe later' also counts: the prompt is shown just once."""
    user = request.bs_user
    if not user.review_prompt_done:
        user.review_prompt_done = True
        user.save(update_fields=["review_prompt_done"])
    return JsonResponse({"success": True})


@require_http_methods(["GET"])
def api_reviews_public(request):
    """Reviews the admin has chosen to show on the home page (no emails, no ids of users)."""
    from django.db.models import Avg, Count
    shown = Review.objects.filter(show_on_home=True)
    agg = shown.aggregate(n=Count("id"), avg=Avg("rating"))
    rows = [{"name": r.display_name or "A BioSpine user", "rating": r.rating, "comment": r.comment,
             "date": r.created_at.date().isoformat()} for r in shown.order_by("-created_at")[:12]]
    resp = JsonResponse({"success": True, "reviews": rows, "count": agg["n"] or 0,
                         "average": round(agg["avg"], 1) if agg["avg"] else None})
    resp["Cache-Control"] = "public, max-age=60"
    return resp


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_user_body(request):
    """Save / change height and weight (Settings -> My body)."""
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    height, weight, problem = bodymod.clean_body(data.get("heightCm"), data.get("weightKg"))
    if problem:
        return json_error(problem, 400)
    if height is None:
        return json_error("Please enter both height and weight.", 400)
    user.height_cm, user.weight_kg, user.body_updated_at = height, weight, timezone.now()
    user.save(update_fields=["height_cm", "weight_kg", "body_updated_at"])
    return JsonResponse({"success": True, "body": _body_payload(user)})


@csrf_exempt
@require_http_methods(["POST"])
@token_required
def api_user_extras(request):
    """Save back-break / quiz / quest / badge progress on the account (merged, never lowered)."""
    data, err = read_json(request)
    if err:
        return err
    user = request.bs_user
    if not throttle(f"extras:{user.pk}", 240, 3600):
        return too_many()
    merged = rewardsmod.merge_extras(user.extras, data.get("extras"))
    user.extras = merged
    user.save(update_fields=["extras"])
    return JsonResponse({"success": True, "extras": merged})
