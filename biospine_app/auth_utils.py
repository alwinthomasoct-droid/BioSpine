"""Token authentication, JSON helpers and rate limiting for the API."""
import hashlib
import json
import logging
import random
import secrets
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from .models import AuthToken, RateLimitHit

log = logging.getLogger(__name__)
TOKEN_DAYS = 30
MAX_BODY = 64 * 1024


def json_error(message, status=400, **extra):
    return JsonResponse({"success": False, "error": message, **extra}, status=status)


def read_json(request):
    """Parse a small JSON object body. Returns (dict, None) or (None, error_response)."""
    if len(request.body) > MAX_BODY:
        return None, json_error("Request too large.", 413)
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None, json_error("Invalid JSON.", 400)
    if not isinstance(data, dict):
        return None, json_error("Invalid JSON.", 400)
    return data, None


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def issue_token(user, request=None):
    key = secrets.token_urlsafe(32)
    AuthToken.objects.create(
        user=user, key_hash=_hash(key), expires_at=timezone.now() + timedelta(days=TOKEN_DAYS),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:200] if request else ""),
    )
    if random.random() < 0.05:   # housekeeping
        AuthToken.objects.filter(expires_at__lt=timezone.now()).delete()
    return key


def authenticate(request):
    """Return (user, token_row) from `Authorization: Bearer <token>`, or (None, None)."""
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if not header.lower().startswith("bearer "):
        return None, None
    key = header[7:].strip()
    if not key:
        return None, None
    tok = AuthToken.objects.select_related("user").filter(key_hash=_hash(key), expires_at__gt=timezone.now()).first()
    if not tok:
        return None, None
    now = timezone.now()
    if now - tok.last_used_at > timedelta(hours=6):          # sliding expiry for active devices
        tok.last_used_at = now
        tok.expires_at = now + timedelta(days=TOKEN_DAYS)
        tok.save(update_fields=["last_used_at", "expires_at"])
    return tok.user, tok


def token_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user, tok = authenticate(request)
        if not user:
            return json_error("Please sign in again.", 401, code="auth")
        request.bs_user, request.bs_token = user, tok
        return view(request, *args, **kwargs)
    return wrapper


def client_ip(request):
    if settings.TRUST_PROXY_HEADERS:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[-1].strip()   # last hop = added by OUR proxy, so it cannot be spoofed by the visitor
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


def throttle(key, limit, window_seconds):
    """Record a hit and return True if the caller is still within `limit` hits per window."""
    now = timezone.now()
    since = now - timedelta(seconds=window_seconds)
    used = RateLimitHit.objects.filter(key=key, created_at__gte=since).count()
    if used >= limit:
        return False
    RateLimitHit.objects.create(key=key)
    if random.random() < 0.02:
        RateLimitHit.objects.filter(created_at__lt=now - timedelta(days=2)).delete()
    return True


def too_many(message="Too many attempts. Please wait a while and try again."):
    return json_error(message, 429, code="rate_limited")
