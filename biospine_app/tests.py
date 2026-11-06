import json
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from . import ai, emails
from .models import AuthToken, ChatMessage, PostureSession, RateLimitHit, UserProfile

PW = "Str0ng-Passw0rd!"


def post(client, url, data=None, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(url, json.dumps(data or {}), content_type="application/json", **headers)


def get(client, url, token=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.get(url, **headers)


def register(client, email="a@example.com"):
    r = post(client, "/api/auth/register", {"email": email, "password": PW})
    assert r.status_code == 200, r.content
    return r.json()["user"]["token"]


def gemini_ok(text="Raise your screen to eye level."):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    return resp


def gemini_err(code, msg="err"):
    resp = mock.Mock(status_code=code, text=msg)
    resp.json.return_value = {"error": {"message": msg}}
    return resp


@override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="")
class AuthTests(TestCase):
    def test_register_login_session_logout(self):
        token = register(self.client)
        self.assertTrue(UserProfile.objects.get(email="a@example.com").password_hash.startswith("pbkdf2"))
        # token is stored hashed, never in clear
        self.assertFalse(AuthToken.objects.filter(key_hash=token).exists())
        self.assertEqual(post(self.client, "/api/auth/session", token=token).status_code, 200)
        self.assertEqual(post(self.client, "/api/auth/logout", token=token).status_code, 200)
        self.assertEqual(post(self.client, "/api/auth/session", token=token).status_code, 401)   # really revoked

    def test_weak_password_rejected(self):
        for pw in ("123456", "password", "short1"):
            r = post(self.client, "/api/auth/register", {"email": "w@example.com", "password": pw})
            self.assertEqual(r.status_code, 400, pw)

    def test_login_generic_error_and_bruteforce_lock(self):
        register(self.client)
        r = post(self.client, "/api/auth/login", {"email": "a@example.com", "password": "wrong-password-1"})
        self.assertEqual(r.status_code, 401)
        r2 = post(self.client, "/api/auth/login", {"email": "nobody@example.com", "password": "wrong-password-1"})
        self.assertEqual(r.json()["error"], r2.json()["error"])          # no user enumeration
        codes = [post(self.client, "/api/auth/login", {"email": "a@example.com", "password": f"bad-pass-{i}"}).status_code for i in range(12)]
        self.assertIn(429, codes)

    def test_legacy_account_without_password_cannot_be_claimed(self):
        UserProfile.objects.create(email="legacy@example.com", password_hash="")
        r = post(self.client, "/api/auth/login", {"email": "legacy@example.com", "password": PW})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(UserProfile.objects.get(email="legacy@example.com").password_hash, "")


class IsolationTests(TestCase):
    """The big security fix: knowing someone's email gives you nothing."""

    def setUp(self):
        self.ta = register(self.client, "alice@example.com")
        self.tb = register(self.client, "bob@example.com")
        alice = UserProfile.objects.get(email="alice@example.com")
        self.chat = ChatMessage.objects.create(user=alice, question="secret question", answer="a")

    def test_endpoints_need_token(self):
        for method, url in [("get", "/api/chat/history?email=alice@example.com"), ("get", "/api/user/export"),
                            ("get", "/api/user/sessions"), ("post", "/api/user/sync"), ("post", "/api/ai/chat"),
                            ("post", "/api/ai/diagnose"), ("post", f"/api/chat/{self.chat.id}/delete")]:
            r = getattr(self.client, method)(url) if method == "get" else post(self.client, url, {"email": "alice@example.com"})
            self.assertEqual(r.status_code, 401, url)

    def test_bob_cannot_read_or_delete_alice_data(self):
        r = get(self.client, "/api/chat/history?email=alice@example.com", self.tb)
        self.assertEqual(r.json()["history"], [])                          # email param is ignored
        self.assertEqual(post(self.client, f"/api/chat/{self.chat.id}/delete", {"email": "alice@example.com"}, self.tb).status_code, 404)
        self.assertTrue(ChatMessage.objects.filter(pk=self.chat.pk).exists())
        # bob's sync with alice's email writes to BOB's account only
        post(self.client, "/api/user/sync", {"email": "alice@example.com", "session": {"duration": 600, "score": 90, "alerts": 1, "avg": 5}}, self.tb)
        self.assertEqual(PostureSession.objects.filter(user__email="alice@example.com").count(), 0)
        self.assertEqual(PostureSession.objects.filter(user__email="bob@example.com").count(), 1)


class SyncTests(TestCase):
    def test_validation_streak_and_pagination(self):
        t = register(self.client)
        r = post(self.client, "/api/user/sync", {"session": {"duration": 3600, "score": 999, "alerts": -5, "avg": 1e9}, "tzOffset": 330}, t)
        self.assertEqual(r.status_code, 200)
        s = PostureSession.objects.get()
        self.assertEqual((s.compliance_score, s.alert_count, s.avg_sagittal_deviation), (100, 0, 90.0))   # clamped
        self.assertEqual(r.json()["streak"]["current"], 1)
        post(self.client, "/api/user/sync", {"session": {"duration": 3, "score": 90}}, t)      # too short: ignored
        self.assertEqual(PostureSession.objects.count(), 1)
        for i in range(5):
            post(self.client, "/api/user/sync", {"session": {"duration": 100 + i, "score": 70, "alerts": 1, "avg": 4}}, t)
        page = get(self.client, "/api/user/sessions?offset=0&limit=4", t).json()
        self.assertEqual((page["total"], len(page["sessions"]), page["hasMore"]), (6, 4, True))
        post(self.client, "/api/user/sync", {"settings": {"angle": 9999, "mode": "evil", "dailyGoal": 5}}, t)
        u = UserProfile.objects.get()
        self.assertEqual((u.warning_angle, u.active_mode, u.daily_goal_minutes), (60.0, "focus", 10))


class AccountTests(TestCase):
    def test_verify_reset_change_delete_export(self):
        t = register(self.client)
        user = UserProfile.objects.get()
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)                                   # verification email sent
        link = emails.make_verify_token(user)
        self.assertEqual(self.client.get(f"/verify-email/{link}/").status_code, 200)
        user.refresh_from_db(); self.assertTrue(user.email_verified)
        self.assertEqual(self.client.get("/verify-email/garbage/").status_code, 400)

        # password reset: link works once, then dies
        post(self.client, "/api/auth/forgot", {"email": "a@example.com"})
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(post(self.client, "/api/auth/forgot", {"email": "ghost@example.com"}).status_code, 200)   # same answer
        self.assertEqual(len(mail.outbox), 2)
        tok = emails.make_reset_token(user)
        self.assertEqual(self.client.post(f"/reset-password/{tok}/", {"password": "n3w-Passw0rd!x", "password2": "mismatch"}).status_code, 200)
        r = self.client.post(f"/reset-password/{tok}/", {"password": "n3w-Passw0rd!x", "password2": "n3w-Passw0rd!x"})
        self.assertIn(b"Password updated", r.content)
        self.assertEqual(self.client.get(f"/reset-password/{tok}/").status_code, 400)       # single use
        self.assertEqual(post(self.client, "/api/auth/session", token=t).status_code, 401)   # old devices signed out
        t2 = post(self.client, "/api/auth/login", {"email": "a@example.com", "password": "n3w-Passw0rd!x"}).json()["user"]["token"]

        # change password
        self.assertEqual(post(self.client, "/api/auth/change-password", {"current": "bad", "new": PW}, t2).status_code, 403)
        self.assertEqual(post(self.client, "/api/auth/change-password", {"current": "n3w-Passw0rd!x", "new": PW}, t2).status_code, 200)

        # export + delete
        ChatMessage.objects.create(user=user, question="q", answer="a")
        data = get(self.client, "/api/user/export", t2).json()
        self.assertEqual(data["account"]["email"], "a@example.com"); self.assertEqual(len(data["aiChats"]), 1)
        self.assertNotIn("password", json.dumps(data).lower())
        self.assertEqual(post(self.client, "/api/auth/delete", {"password": "wrong"}, t2).status_code, 403)
        self.assertEqual(post(self.client, "/api/auth/delete", {"password": PW}, t2).status_code, 200)
        self.assertEqual((UserProfile.objects.count(), ChatMessage.objects.count(), AuthToken.objects.count()), (0, 0, 0))

    def test_unsubscribe_and_contact(self):
        register(self.client)
        u = UserProfile.objects.get()
        self.client.get(f"/unsubscribe/{emails.make_unsub_token(u)}/")
        u.refresh_from_db(); self.assertFalse(u.weekly_email)
        r = self.client.post("/contact/", {"name": "Tom", "email": "t@example.com", "message": "Hello there"})
        self.assertContains(r, "Thank you")
        self.client.post("/contact/", {"name": "Bot", "email": "b@example.com", "message": "spam spam", "website": "x"})
        from .models import ContactMessage
        self.assertEqual(ContactMessage.objects.count(), 1)                    # honeypot caught the bot


@override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="")
class AITests(TestCase):
    def setUp(self):
        ai._working_model = None
        self.t = register(self.client)

    def test_chat_success_saves_history_and_uses_header_key(self):
        with mock.patch("biospine_app.ai.requests.post", return_value=gemini_ok("Tuck your chin slightly.")) as p:
            r = post(self.client, "/api/ai/chat", {"query": "neck hurts", "liveDev": "22.5", "livePostureType": "Forward", "compliance": "55%"}, self.t)
        self.assertEqual(r.json()["reply"], "Tuck your chin slightly.")
        self.assertEqual(ChatMessage.objects.count(), 1)
        args, kwargs = p.call_args
        self.assertNotIn("key=", args[0])                                       # key is NOT in the URL
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertIn("systemInstruction", kwargs["json"])

    def test_retired_model_falls_through_to_next_model(self):
        calls = []

        def fake(url, **kw):
            calls.append(url)
            return gemini_err(404, "model not found") if len(calls) == 1 else gemini_ok("Works on 2nd model")
        with mock.patch("biospine_app.ai.requests.post", side_effect=fake):
            r = post(self.client, "/api/ai/chat", {"query": "hi"}, self.t)
        self.assertEqual(r.json()["reply"], "Works on 2nd model")
        self.assertEqual(len(calls), 2)
        self.assertEqual(ai._working_model, r.json()["model"])

    def test_total_failure_is_honest_not_silent(self):
        with mock.patch("biospine_app.ai.requests.post", return_value=gemini_err(404, "gone")):
            r = post(self.client, "/api/ai/chat", {"query": "hi", "livePostureType": "Forward Slouch", "liveDev": 25}, self.t)
        body = r.json()
        self.assertEqual(r.status_code, 503)
        self.assertFalse(body["success"])
        self.assertIn("tip", body)                                              # labelled offline tip
        self.assertEqual(ChatMessage.objects.count(), 0)                        # fake answers are not stored as chats

    def test_bad_key_message_and_empty_or_blocked(self):
        with mock.patch("biospine_app.ai.requests.post", return_value=gemini_err(403, "API key not valid")):
            self.assertEqual(post(self.client, "/api/ai/chat", {"query": "hi"}, self.t).json()["code"], "bad_key")
        blocked = mock.Mock(status_code=200); blocked.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        with mock.patch("biospine_app.ai.requests.post", return_value=blocked):
            self.assertEqual(post(self.client, "/api/ai/chat", {"query": "hi"}, self.t).json()["code"], "blocked")

    def test_diagnose_html_is_escaped(self):
        evil = json.dumps({"assessment": "<script>alert(1)</script> forward head", "workstation": ["<img src=x onerror=alert(1)>"],
                           "routine": ["Chin tucks x10"], "note": "Great job"})
        with mock.patch("biospine_app.ai.requests.post", return_value=gemini_ok(evil)):
            r = post(self.client, "/api/ai/diagnose", {"duration": "10:00", "compliance": 70, "avgDev": "12", "maxDev": "30", "alerts": 3,
                                                       "neckLoad": "27 lbs", "mode": "<b>x</b>", "postureBreakdown": {"forward": "30s"}}, self.t)
        html = r.json()["html"]
        self.assertNotIn("<script", html); self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html); self.assertIn("Chin tucks", html)

    @override_settings(AI_CHAT_PER_HOUR=2)
    def test_ai_rate_limit(self):
        with mock.patch("biospine_app.ai.requests.post", return_value=gemini_ok()):
            codes = [post(self.client, "/api/ai/chat", {"query": f"q{i}"}, self.t).status_code for i in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_unverified_blocked_when_required(self):
        r = post(self.client, "/api/ai/chat", {"query": "hi"}, self.t)
        self.assertEqual((r.status_code, r.json()["code"]), (403, "verify"))

    @override_settings(GEMINI_API_KEY="")
    def test_not_configured(self):
        r = post(self.client, "/api/ai/chat", {"query": "hi"}, self.t)
        self.assertEqual(r.json()["code"], "not_configured")


class PagesAndCommandsTests(TestCase):
    def test_public_pages_and_headers(self):
        for url in ["/", "/privacy/", "/terms/", "/disclaimer/", "/contact/", "/robots.txt", "/sitemap.xml", "/healthz", "/sw.js"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.get("/")
        self.assertIn("script-src 'self' https://cdnjs.cloudflare.com", r["Content-Security-Policy"])
        self.assertEqual(self.client.get("/nope/").status_code, 404)

    def test_staff_dashboard_still_protected(self):
        self.assertEqual(self.client.get("/staff/analytics/").status_code, 302)

    def test_weekly_report_and_backup_commands(self):
        from django.core.management import call_command
        import tempfile, pathlib
        t = register(self.client)
        u = UserProfile.objects.get(); u.email_verified = True; u.save()
        PostureSession.objects.create(user=u, duration_seconds=1800, compliance_score=80, alert_count=2)
        mail.outbox.clear()
        call_command("send_weekly_reports")
        self.assertEqual(len(mail.outbox), 1); self.assertIn("Unsubscribe", mail.outbox[0].body)
        call_command("send_weekly_reports")
        self.assertEqual(len(mail.outbox), 1)                                   # not sent twice in a week
        with tempfile.TemporaryDirectory() as d, override_settings(BACKUP_DIR=pathlib.Path(d), BACKUP_KEEP=1):
            call_command("backup_data"); call_command("backup_data")
            self.assertEqual(len(list(pathlib.Path(d).glob("*.json.gz"))), 1)   # rotation keeps only the newest

    @override_settings(CRON_SECRET="s3cret")
    def test_cron_endpoint(self):
        self.assertEqual(self.client.get("/cron/weekly-report/?key=wrong").status_code, 403)
        self.assertEqual(self.client.get("/cron/weekly-report/?key=s3cret").status_code, 200)


# ---------------------------------------------------------------------------
# v5: reviews, admin reports, AI switch, honest emails
# ---------------------------------------------------------------------------
from django.contrib.auth import get_user_model
from .models import Review


def _sessions(client, token, n):
    for i in range(n):
        post(client, "/api/user/sync", {"session": {"duration": 600 + i, "score": 70 + i, "alerts": 2, "avg": 5}}, token)


class ReviewTests(TestCase):
    def test_prompt_due_only_after_fifth_session_and_only_once(self):
        t = register(self.client)
        _sessions(self.client, t, 4)
        self.assertFalse(post(self.client, "/api/auth/session", token=t).json()["user"]["review"]["promptDue"])
        r = post(self.client, "/api/user/sync", {"session": {"duration": 900, "score": 80, "alerts": 1, "avg": 4}}, t)
        self.assertTrue(r.json()["reviewPromptDue"])
        self.assertTrue(post(self.client, "/api/auth/session", token=t).json()["user"]["review"]["promptDue"])
        post(self.client, "/api/review/dismiss", token=t)                       # "maybe later" = asked once, never again
        self.assertFalse(post(self.client, "/api/auth/session", token=t).json()["user"]["review"]["promptDue"])
        r = post(self.client, "/api/user/sync", {"session": {"duration": 900, "score": 80, "alerts": 1, "avg": 4}}, t)
        self.assertFalse(r.json()["reviewPromptDue"])

    def test_submit_validation_and_admin_controls_visibility(self):
        t = register(self.client)
        self.assertEqual(post(self.client, "/api/review", {"rating": 9}, t).status_code, 400)
        self.assertEqual(post(self.client, "/api/review", {"rating": "x"}, t).status_code, 400)
        self.assertEqual(post(self.client, "/api/review", {"rating": 5, "name": "Priya", "comment": "<b>Great</b>"}, t).status_code, 200)
        rv = Review.objects.get()
        self.assertFalse(rv.show_on_home)                                       # nothing is public until an admin approves it
        self.assertEqual(get(self.client, "/api/reviews").json()["reviews"], [])
        rv.show_on_home = True
        rv.save()
        pub = get(self.client, "/api/reviews").json()
        self.assertEqual((pub["count"], pub["average"], pub["reviews"][0]["name"]), (1, 5.0, "Priya"))
        self.assertNotIn("a@example.com", json.dumps(pub))                      # never leaks the email
        # editing it sends it back for approval
        post(self.client, "/api/review", {"rating": 4, "comment": "Edited"}, t)
        self.assertEqual(get(self.client, "/api/reviews").json()["reviews"], [])
        self.assertEqual(Review.objects.count(), 1)

    def test_review_requires_login_and_is_deleted_with_account(self):
        self.assertEqual(post(self.client, "/api/review", {"rating": 5}).status_code, 401)
        t = register(self.client)
        post(self.client, "/api/review", {"rating": 5}, t)
        UserProfile.objects.get().delete()
        self.assertEqual(Review.objects.count(), 0)


class StaffReportTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.admin = U.objects.create_user("boss", "boss@example.com", "pw-boss-12345", is_staff=True, is_superuser=True)
        self.t = register(self.client, "client@example.com")
        _sessions(self.client, self.t, 6)
        post(self.client, "/api/review", {"rating": 4, "name": "Sam", "comment": "Nice"}, self.t)
        self.uid = UserProfile.objects.get(email="client@example.com").pk

    def test_reports_need_staff(self):
        for url in (f"/staff/analytics/user/{self.uid}/report.xlsx", "/staff/analytics/report.pdf", "/staff/analytics/reviews/"):
            self.assertEqual(self.client.get(url).status_code, 302, url)       # redirected to the admin login

    def test_excel_and_pdf_reports(self):
        self.client.force_login(self.admin)
        for url, magic in ((f"/staff/analytics/user/{self.uid}/report.xlsx", b"PK"), (f"/staff/analytics/user/{self.uid}/report.pdf", b"%PDF"),
                           ("/staff/analytics/report.xlsx", b"PK"), ("/staff/analytics/report.pdf?weeks=8", b"%PDF")):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertTrue(r.content.startswith(magic), url)
            self.assertIn("attachment", r["Content-Disposition"])
        self.assertEqual(self.client.get("/staff/analytics/report.docx").status_code, 404)
        self.assertEqual(self.client.get("/staff/analytics/user/99999/report.pdf").status_code, 404)

    def test_review_moderation_page_and_dashboard(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/staff/analytics/reviews/"), "Show on home page")
        rid = Review.objects.get().pk
        self.assertEqual(self.client.post(f"/staff/analytics/reviews/{rid}/toggle", {"show": "1"}).status_code, 302)
        self.assertTrue(Review.objects.get().show_on_home)
        self.assertEqual(self.client.get("/staff/analytics/").status_code, 200)
        self.assertEqual(self.client.get(f"/staff/analytics/user/{self.uid}/").status_code, 200)

    def test_platform_series_averages(self):
        from . import analytics
        weekly = analytics.weekly_platform_series(8)
        self.assertEqual(len(weekly), 1)
        self.assertEqual((weekly[0]["users"], weekly[0]["sessions"]), (1, 6))


class AiSwitchTests(TestCase):
    @override_settings(AI_ENABLED=False, GEMINI_API_KEY="k")
    def test_ai_can_be_removed_completely(self):
        t = register(self.client)
        r = post(self.client, "/api/ai/chat", {"question": "hi"}, t)
        self.assertEqual((r.status_code, r.json()["code"]), (404, "ai_off"))
        self.assertEqual(post(self.client, "/api/ai/diagnose", {"summary": {}}, t).status_code, 404)
        page = self.client.get("/").content.decode()
        self.assertIn('data-ai="0"', page)
        self.assertNotIn("AI Physio coach", page)

    @override_settings(AI_ENABLED=True, GEMINI_API_KEY="")
    def test_ai_hidden_when_no_key(self):
        self.assertIn('data-ai="0"', self.client.get("/").content.decode())

    @override_settings(AI_ENABLED=True, GEMINI_API_KEY="k")
    def test_ai_shown_when_configured(self):
        self.assertIn('data-ai="1"', self.client.get("/").content.decode())


class EmailHonestyTests(TestCase):
    @override_settings(EMAIL_CONFIGURED=True)
    def test_register_reports_real_email_result(self):
        r = post(self.client, "/api/auth/register", {"email": "e1@example.com", "password": PW})
        self.assertTrue(r.json()["emailSent"])
        self.assertEqual(len(mail.outbox), 1)
        with mock.patch("biospine_app.emails.send_verification", return_value=False):
            r = post(self.client, "/api/auth/register", {"email": "e2@example.com", "password": PW})
            self.assertFalse(r.json()["emailSent"])

    @override_settings(EMAIL_CONFIGURED=False)
    def test_unconfigured_email_is_not_reported_as_sent(self):
        r = post(self.client, "/api/auth/register", {"email": "e3@example.com", "password": PW})
        self.assertFalse(r.json()["emailSent"])
        t = r.json()["user"]["token"]
        self.assertEqual(post(self.client, "/api/auth/resend-verification", token=t).status_code, 503)

    @override_settings(EMAIL_CONFIGURED=True)
    def test_resend_failure_is_an_error_not_a_fake_success(self):
        t = register(self.client, "e4@example.com")
        with mock.patch("biospine_app.emails.send_verification", return_value=False):
            self.assertEqual(post(self.client, "/api/auth/resend-verification", token=t).status_code, 503)

    @override_settings(EMAIL_CONFIGURED=True)
    def test_check_email_command(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("check_email", "me@example.com", stdout=out)
        self.assertIn("accepted", out.getvalue())
        self.assertEqual(mail.outbox[-1].to, ["me@example.com"])


# ---------------------------------------------------------------------------
# v5.1: height / weight / BMI and the tabbed staff analytics
# ---------------------------------------------------------------------------
class BodyTests(TestCase):
    def test_bmi_math(self):
        from .body import bmi_info, clean_body
        i = bmi_info(170, 70)
        self.assertEqual((i["bmi"], i["key"]), (24.2, "healthy"))
        self.assertEqual(bmi_info(160, 45)["key"], "under")
        self.assertEqual(bmi_info(165, 100)["key"], "obese")
        self.assertIsNone(bmi_info(None, 70))
        self.assertEqual(clean_body("", "")[2], None)
        self.assertIn("both", clean_body(170, "")[2])
        self.assertIn("Height", clean_body(20, 70)[2])

    def test_register_stores_body_and_returns_bmi(self):
        r = post(self.client, "/api/auth/register", {"email": "b1@example.com", "password": PW, "heightCm": 170, "weightKg": 70})
        self.assertEqual(r.status_code, 200)
        body = r.json()["user"]["body"]
        self.assertEqual((body["heightCm"], body["weightKg"], body["info"]["bmi"]), (170.0, 70.0, 24.2))
        u = UserProfile.objects.get(email="b1@example.com")
        self.assertEqual((u.height_cm, u.weight_kg), (170.0, 70.0))

    def test_register_rejects_nonsense_and_allows_missing(self):
        self.assertEqual(post(self.client, "/api/auth/register", {"email": "b2@example.com", "password": PW, "heightCm": 5, "weightKg": 70}).status_code, 400)
        self.assertEqual(post(self.client, "/api/auth/register", {"email": "b3@example.com", "password": PW, "heightCm": "abc", "weightKg": 70}).status_code, 400)
        self.assertEqual(post(self.client, "/api/auth/register", {"email": "b4@example.com", "password": PW, "heightCm": 170}).status_code, 400)
        self.assertFalse(UserProfile.objects.filter(email__in=["b2@example.com", "b3@example.com", "b4@example.com"]).exists())
        r = post(self.client, "/api/auth/register", {"email": "b5@example.com", "password": PW})     # older clients still work
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["user"]["body"]["info"])

    def test_update_body_endpoint(self):
        t = register(self.client, "b6@example.com")
        self.assertEqual(post(self.client, "/api/user/body", {"heightCm": 160, "weightKg": 90}).status_code, 401)
        r = post(self.client, "/api/user/body", {"heightCm": 160, "weightKg": 90}, t)
        self.assertEqual(r.json()["body"]["info"]["key"], "obese")
        self.assertEqual(post(self.client, "/api/user/body", {"heightCm": 160}, t).status_code, 400)
        self.assertEqual(UserProfile.objects.get(email="b6@example.com").weight_kg, 90.0)


class StaffTabsTests(TestCase):
    TABS = ["/staff/analytics/", "/staff/analytics/users/", "/staff/analytics/engagement/", "/staff/analytics/posture/",
            "/staff/analytics/time/", "/staff/analytics/body/", "/staff/analytics/reviews/", "/staff/analytics/reports/"]

    def setUp(self):
        U = get_user_model()
        self.admin = U.objects.create_user("boss2", "boss2@example.com", "pw-boss-12345", is_staff=True, is_superuser=True)
        r = post(self.client, "/api/auth/register", {"email": "p1@example.com", "password": PW, "heightCm": 170, "weightKg": 65})
        self.t = r.json()["user"]["token"]
        _sessions(self.client, self.t, 7)
        register(self.client, "p2@example.com")                       # a user with no sessions and no body data
        self.uid = UserProfile.objects.get(email="p1@example.com").pk

    def test_every_tab_needs_staff(self):
        for url in self.TABS + [f"/staff/analytics/user/{self.uid}/"]:
            self.assertEqual(self.client.get(url).status_code, 302, url)

    def test_every_tab_renders(self):
        self.client.force_login(self.admin)
        for url in self.TABS:
            r = self.client.get(url + "?tz=Asia/Kolkata")
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, "Posture quality")                  # the tab bar is on every page

    def test_users_tab_lists_profiles_and_filters(self):
        self.client.force_login(self.admin)
        r = self.client.get("/staff/analytics/users/")
        self.assertContains(r, "p1@example.com")
        self.assertContains(r, "BMI 22.5")
        only = self.client.get("/staff/analytics/users/?bmi=none")
        self.assertContains(only, "p2@example.com")
        self.assertNotContains(only, "p1@example.com")
        self.assertEqual(self.client.get("/staff/analytics/users/?q=p1&sort=bmi&dir=asc&view=table").status_code, 200)

    def test_profile_page_shows_what_the_user_sees(self):
        self.client.force_login(self.admin)
        for days in ("7", "30", "90", "0", "bogus"):
            self.assertEqual(self.client.get(f"/staff/analytics/user/{self.uid}/?days={days}").status_code, 200, days)
        r = self.client.get(f"/staff/analytics/user/{self.uid}/")
        self.assertContains(r, "Day by day")
        self.assertContains(r, "Time slots")
        self.assertContains(r, "Avg deviation")
        self.assertContains(r, "Healthy weight")
        # a user with no sessions must not crash the page either
        empty = UserProfile.objects.get(email="p2@example.com").pk
        self.assertEqual(self.client.get(f"/staff/analytics/user/{empty}/").status_code, 200)

    def test_users_csv_has_body_columns(self):
        self.client.force_login(self.admin)
        body = self.client.get("/staff/analytics/export/users.csv").content.decode()
        self.assertIn("height_cm,weight_kg,bmi", body)
        self.assertIn("170.0,65.0,22.5", body)

    def test_user_report_contains_bmi(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/staff/analytics/user/{self.uid}/report.pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))


# ---------------------------------------------------------------------------
# v5.5: full session details for staff, retry-safe uploads, progress that follows the account
# ---------------------------------------------------------------------------
import time as _time


def _full_session(cid="sabc123", minutes=30, ago_minutes=120, **extra):
    now_ms = int(_time.time() * 1000)
    end = now_ms - ago_minutes * 60000
    s = {"id": cid, "start": end - minutes * 60000, "end": end, "duration": minutes * 60, "score": 72, "alerts": 5, "avg": 9.3, "median": 8.0,
         "max": 31.0, "avgRoll": 3.0, "maxRoll": 11.0, "peakLoad": 41, "mode": "focus", "angle": 18, "source": "ble",
         "strain": {"forward": 300, "left": 60}, "trend": {"step": 15, "pitch": [(i % 25) - 3 for i in range(120)], "roll": [2] * 120, "bad": [i % 2 for i in range(120)]},
         "events": [{"t": end, "type": "bad", "title": "Forward slouch", "detail": "24 deg"}]}
    s.update(extra)
    return s


class SessionDetailTests(TestCase):
    def test_details_are_stored_and_re_sending_is_safe(self):
        t = register(self.client, "d1@example.com")
        r = post(self.client, "/api/user/sync", {"session": _full_session()}, t)
        self.assertTrue(r.json()["success"])
        self.assertFalse(r.json()["duplicate"])
        s = PostureSession.objects.get()
        self.assertEqual((s.client_id, s.mode, s.source, s.peak_load, s.warning_angle), ("sabc123", "focus", "device", 41, 18.0))
        self.assertEqual(len(s.trend["pitch"]), 120)
        self.assertEqual(s.strain["forward"], 300.0)
        self.assertEqual(s.events[0]["title"], "Forward slouch")
        self.assertEqual(s.start_time, s.started_at)
        self.assertLess(abs((s.date - s.ended_at).total_seconds()), 1)          # the REAL end time, not the upload time
        # the browser sends the same session again (retry): nothing is created twice
        r2 = post(self.client, "/api/user/sync", {"session": _full_session()}, t)
        self.assertTrue(r2.json()["duplicate"])
        self.assertEqual(PostureSession.objects.count(), 1)

    def test_garbage_is_cleaned(self):
        t = register(self.client, "d2@example.com")
        post(self.client, "/api/user/sync", {"session": {"duration": 2, "score": 50}}, t)
        self.assertEqual(PostureSession.objects.count(), 0)                     # too short
        bad = _full_session(cid="x y;drop", trend={"step": "abc", "pitch": ["a", 400, None], "roll": [], "bad": []}, mode="evil", score=900)
        post(self.client, "/api/user/sync", {"session": bad}, t)
        s = PostureSession.objects.get()
        self.assertEqual((s.client_id, s.mode, s.compliance_score), ("", "", 100))
        self.assertEqual(s.trend["pitch"], [0.0, 90.0, 0.0])

    def test_demo_session_flag(self):
        t = register(self.client, "d3@example.com")
        post(self.client, "/api/user/sync", {"session": _full_session(cid="sdemo1", source="demo")}, t)
        self.assertEqual(PostureSession.objects.get().source, "demo")

    def test_login_payload_has_account_wide_xp_and_stats(self):
        from . import rewards
        t = register(self.client, "d4@example.com")
        post(self.client, "/api/user/sync", {"session": _full_session(cid="sa1", minutes=30)}, t)
        post(self.client, "/api/user/sync", {"session": _full_session(cid="sa2", minutes=20, ago_minutes=300, score=95)}, t)
        u = post(self.client, "/api/auth/session", token=t).json()["user"]
        self.assertEqual(u["sessionXp"], rewards.session_xp(1800, 72) + rewards.session_xp(1200, 95))
        self.assertEqual((u["stats"]["sessions"], u["stats"]["bestScore"]), (2, 95))

    def test_progress_extras_follow_the_account(self):
        t = register(self.client, "d5@example.com")
        post(self.client, "/api/user/extras", {"extras": {"breaks": 3, "earned": {"first": "2026-11-01"}, "breakDays": {"2026-11-01": 2}, "quizBest": 4, "lastLevel": 3}}, t)
        # another device pushes a different, partly older state: nothing is lost
        r = post(self.client, "/api/user/extras", {"extras": {"breaks": 1, "earned": {"st3": "2026-11-02"}, "breakDays": {"2026-11-02": 1}, "quizBest": 2}}, t)
        m = r.json()["extras"]
        self.assertEqual((m["breaks"], m["quizBest"], m["lastLevel"]), (3, 4, 3))
        self.assertEqual(set(m["earned"]), {"first", "st3"})
        self.assertEqual(m["breakDays"], {"2026-11-01": 2, "2026-11-02": 1})
        u = post(self.client, "/api/auth/session", token=t).json()["user"]          # what a NEW device receives at login
        self.assertEqual(u["extras"]["breaks"], 3)
        self.assertEqual(post(self.client, "/api/user/extras", {"extras": {}}).status_code, 401)

    def test_pure_helpers(self):
        from . import rewards, session_data
        self.assertEqual(rewards.session_xp(1800, 80), 58)
        self.assertEqual(rewards.session_xp(700, 95), 47)
        self.assertEqual(rewards.session_xp(3, 99), 0)
        self.assertIsNone(session_data.clean_trend({"pitch": [1]}))
        self.assertEqual(len(session_data.clean_trend({"step": 2, "pitch": list(range(500)), "roll": [0] * 500, "bad": [0] * 500})["pitch"]), 100)


class StaffSessionViewTests(TestCase):
    def setUp(self):
        U = get_user_model()
        self.admin = U.objects.create_user("boss3", "boss3@example.com", "pw-boss-12345", is_staff=True, is_superuser=True)
        self.t = register(self.client, "s1@example.com")
        for i, ago in enumerate((60, 400, 900)):
            post(self.client, "/api/user/sync", {"session": _full_session(cid=f"s{i}abc", ago_minutes=ago)}, self.t)
        post(self.client, "/api/user/sync", {"session": {"duration": 600, "score": 60, "alerts": 1, "avg": 5}}, self.t)    # an old-style summary-only session
        self.uid = UserProfile.objects.get(email="s1@example.com").pk
        self.sid = PostureSession.objects.filter(user_id=self.uid).exclude(trend__isnull=True).first().pk

    def test_profile_shows_time_periods_with_graphs(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/staff/analytics/user/{self.uid}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Open full details and events")
        self.assertContains(r, "<svg", html=False)
        self.assertContains(r, "No graph stored for this session")             # the summary-only session

    def test_session_page(self):
        self.client.force_login(self.admin)
        r = self.client.get(f"/staff/analytics/user/{self.uid}/session/{self.sid}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Forward slouch")
        self.assertContains(r, "Lean angle during this time period")
        self.assertEqual(self.client.get(f"/staff/analytics/user/{self.uid}/session/999999/").status_code, 404)
        self.assertEqual(self.client.get(f"/staff/analytics/user/999999/session/{self.sid}/").status_code, 404)

    def test_session_page_needs_staff(self):
        self.assertEqual(self.client.get(f"/staff/analytics/user/{self.uid}/session/{self.sid}/").status_code, 302)

    def test_user_report_has_graph_sheets_and_pdf(self):
        import io
        import openpyxl
        self.client.force_login(self.admin)
        x = self.client.get(f"/staff/analytics/user/{self.uid}/report.xlsx")
        wb = openpyxl.load_workbook(io.BytesIO(x.content))
        graph_sheets = [n for n in wb.sheetnames if n.startswith("S") and n[1:2].isdigit()]
        self.assertEqual(len(graph_sheets), 3)
        self.assertIn("Time periods by day", wb.sheetnames)
        self.assertEqual(wb["Sessions"].max_row, 5)                              # header + 4 sessions
        self.assertTrue(self.client.get(f"/staff/analytics/user/{self.uid}/report.pdf").content.startswith(b"%PDF"))


class ReviewAnyTimeTests(TestCase):
    def test_login_payload_returns_my_review_so_it_can_be_edited_any_time(self):
        t = register(self.client, "rv1@example.com")
        self.assertIsNone(post(self.client, "/api/auth/session", token=t).json()["user"]["review"]["mine"])
        post(self.client, "/api/review", {"rating": 4, "name": "Sam", "comment": "Good"}, t)
        mine = post(self.client, "/api/auth/session", token=t).json()["user"]["review"]["mine"]
        self.assertEqual((mine["rating"], mine["name"], mine["comment"]), (4, "Sam", "Good"))
        post(self.client, "/api/review", {"rating": 5, "name": "Sam", "comment": "Better"}, t)       # editing is allowed any time
        self.assertEqual(Review.objects.count(), 1)
        self.assertEqual(Review.objects.get().rating, 5)

    def test_buzzer_setting_is_gone_from_the_page(self):
        page = self.client.get("/").content.decode()
        self.assertNotIn("buzzerToggle", page)
        self.assertNotIn("testBuzzBtn", page)
        self.assertIn("sideReviewBtn", page)


class LogoTests(TestCase):
    def test_logo_is_used_on_the_main_page_and_favicon_redirects(self):
        page = self.client.get("/").content.decode()
        self.assertIn("img/logo-full-small.png", page)
        self.assertIn("img/favicon.ico", page)
        self.assertNotIn("ARK Spine", page)
        r = self.client.get("/favicon.ico")
        self.assertEqual((r.status_code, r["Location"]), (301, "/static/img/favicon.ico"))

    def test_emails_carry_the_logo(self):
        from . import emails
        self.assertIn("logo-full-small.png", emails._wrap("Hello", "<p>x</p>"))
