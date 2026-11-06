from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class UserProfile(models.Model):
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255, blank=True, default="")
    session_token = models.CharField(max_length=64, blank=True, default="")   # legacy (unused); see AuthToken
    created_at = models.DateTimeField(auto_now_add=True)
    warning_angle = models.FloatField(default=18.0)
    safe_zone = models.FloatField(default=3.0)
    lateral_limit = models.FloatField(default=12.0)
    active_mode = models.CharField(max_length=20, default="focus")

    # --- Gamified daily streak ---
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_streak_date = models.DateField(null=True, blank=True)

    # --- v4: account health, goals, email preferences ---
    email_verified = models.BooleanField(default=False)
    weekly_email = models.BooleanField(default=True)
    daily_goal_minutes = models.IntegerField(default=120)
    last_weekly_email_at = models.DateTimeField(null=True, blank=True)

    # --- v5: the one-time "how are we doing?" prompt (shown after the 5th saved session, then never again) ---
    review_prompt_done = models.BooleanField(default=False)

    # --- v5.1: body measurements asked at sign-up (optional in the database so older accounts keep working) ---
    height_cm = models.FloatField(null=True, blank=True)
    weight_kg = models.FloatField(null=True, blank=True)
    body_updated_at = models.DateTimeField(null=True, blank=True)

    # --- v5.5: progress that follows the account to every device (back breaks, quiz, quests, badges) ---
    extras = models.JSONField(default=dict, blank=True)

    @property
    def body(self):
        """BMI details (dict) or None when height / weight are missing."""
        from .body import bmi_info
        return bmi_info(self.height_cm, self.weight_kg)

    def set_password(self, raw_password):
        self.password_hash = make_password(raw_password)

    def check_password(self, raw_password):
        if not self.password_hash:
            return False
        return check_password(raw_password, self.password_hash)

    def __str__(self):
        return self.email


class AuthToken(models.Model):
    """One row per signed-in device. Only a SHA-256 hash of the token is stored, so a database
    leak does not let anybody impersonate users. Tokens expire and can be revoked (sign-out)."""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="tokens")
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(auto_now_add=True)
    user_agent = models.CharField(max_length=200, blank=True, default="")

    def __str__(self):
        return f"token for {self.user.email}"


class PostureSession(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="sessions")
    date = models.DateTimeField(auto_now_add=True, db_index=True)
    duration_seconds = models.IntegerField(default=0)
    compliance_score = models.IntegerField(default=0)
    alert_count = models.IntegerField(default=0)
    avg_sagittal_deviation = models.FloatField(default=0.0)

    # --- v5.5: the details staff need to see WHEN and HOW a session went ---
    client_id = models.CharField(max_length=40, blank=True, default="")          # id made by the browser, makes re-sending safe
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=12, blank=True, default="device")      # device / demo
    mode = models.CharField(max_length=12, blank=True, default="")
    warning_angle = models.FloatField(null=True, blank=True)                    # alert angle that was set during the session
    median_dev = models.FloatField(null=True, blank=True)
    max_dev = models.FloatField(null=True, blank=True)
    avg_roll = models.FloatField(null=True, blank=True)
    max_roll = models.FloatField(null=True, blank=True)
    peak_load = models.IntegerField(null=True, blank=True)
    strain = models.JSONField(null=True, blank=True)       # seconds in each slouch type
    trend = models.JSONField(null=True, blank=True)        # {"step": seconds, "pitch": [...], "roll": [...], "bad": [...]}
    events = models.JSONField(null=True, blank=True)       # a short log of alerts / corrections

    class Meta:
        ordering = ["-date"]
        constraints = [models.UniqueConstraint(fields=["user", "client_id"], condition=~models.Q(client_id=""),
                                               name="uniq_session_client_id")]

    @property
    def start_time(self):
        from datetime import timedelta
        return self.started_at or (self.ended_at or self.date) - timedelta(seconds=self.duration_seconds)

    @property
    def end_time(self):
        return self.ended_at or self.date

    def __str__(self):
        return f"{self.user.email} - {self.compliance_score}%"


class ChatMessage(models.Model):
    """One turn of the AI Physio chat, stored so the user can revisit it from the Chats menu."""
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="chat_messages")
    created_at = models.DateTimeField(auto_now_add=True)
    question = models.TextField()
    answer = models.TextField(blank=True, default="")
    context = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email}: {self.question[:40]}"


class RateLimitHit(models.Model):
    """Tiny database-backed rate limiter (works across several server processes)."""
    key = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["key", "created_at"])]


class ContactMessage(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    message = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class Review(models.Model):
    """A client review. It is only shown on the public home page once an admin ticks `show_on_home`."""
    user = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name="review")
    rating = models.PositiveSmallIntegerField(default=5)                    # 1-5 stars
    comment = models.TextField(max_length=600, blank=True, default="")
    display_name = models.CharField(max_length=40, blank=True, default="")   # what visitors see (never the email)
    created_at = models.DateTimeField(auto_now_add=True)
    show_on_home = models.BooleanField(default=False, help_text="Tick to show this review on the public home page.")
    admin_note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}* by {self.display_name or self.user.email}"
