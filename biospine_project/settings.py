"""
BioSpine settings.

Everything that differs between your laptop and the live website is read from
environment variables (a local `.env` file, or the dashboard of your host).
See `.env.example` for the full list.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool("DEBUG", False)          # safe default: OFF. Set DEBUG=True only on your own computer.

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
    else:
        raise ImproperlyConfigured(
            "SECRET_KEY is not set. Generate one with:  python -c \"from django.core.management.utils "
            "import get_random_secret_key as g; print(g())\"  and put it in your environment / .env file."
        )

SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
SITE_NAME = os.getenv("SITE_NAME", "BioSpine")
OPERATOR_NAME = os.getenv("OPERATOR_NAME", "the BioSpine team")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS.append(_render_host)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", SITE_URL if SITE_URL.startswith("https://") else "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "biospine_app",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "biospine_app.middleware.SecurityHeadersMiddleware",
]

# CORS is OFF by default (the website and its API live on the same domain, so it isn't needed).
# Only switch it on if you build a separate front-end:  CORS_ALLOWED_ORIGINS=https://my-other-site.com
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
if CORS_ALLOWED_ORIGINS:
    INSTALLED_APPS.insert(-1, "corsheaders")
    MIDDLEWARE.insert(0, "corsheaders.middleware.CorsMiddleware")
    CORS_ALLOW_HEADERS = ["authorization", "content-type"]

ROOT_URLCONF = "biospine_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "biospine_app.context.site",
            ],
        },
    },
]

WSGI_APPLICATION = "biospine_project.wsgi.application"

# --------------------------------------------------------------------------
# Database: SQLite on your laptop, PostgreSQL on the live site (set DATABASE_URL)
# --------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("#") or "://" not in DATABASE_URL[:20]:   # an empty value or a stray comment means: use the local SQLite file
    DATABASE_URL = ""
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, conn_health_checks=True)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files (served by WhiteNoise)
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# HTTPS / cookie hardening (only when DEBUG is off, i.e. on the live site)
# --------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")   # host terminates TLS and forwards this header
    SECURE_SSL_REDIRECT = env_bool("FORCE_HTTPS", True)
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("HSTS_SECONDS", 31536000) if SECURE_SSL_REDIRECT else 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", not DEBUG)   # read the real visitor IP from X-Forwarded-For

# --------------------------------------------------------------------------
# Email (verification, password reset, weekly report)
# --------------------------------------------------------------------------
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = env_int("EMAIL_PORT", 587)
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", EMAIL_PORT == 465)          # port 465 = implicit SSL
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", not EMAIL_USE_SSL)         # port 587 = STARTTLS
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"   # prints emails to the terminal / logs
# Many providers (Gmail, Brevo...) only deliver mail whose "from" address is the account you log in with,
# so when DEFAULT_FROM_EMAIL is not set we fall back to the SMTP login instead of an invalid @localhost address.
_default_from = os.getenv("EMAIL_HOST_USER", "") if EMAIL_HOST else ""
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL") or (f"{SITE_NAME} <{_default_from}>" if "@" in _default_from else f"{SITE_NAME} <no-reply@localhost>")
EMAIL_TIMEOUT = 10
EMAIL_CONFIGURED = bool(EMAIL_HOST)       # False = emails are only printed in the server log (local testing)

# --------------------------------------------------------------------------
# AI (Google Gemini) + abuse limits
# --------------------------------------------------------------------------
# Master switch for the AI assistant. Set AI_ENABLED=False to remove the AI Physio, AI diagnosis and the
# "Chats" tab from the whole website. With no GEMINI_API_KEY the AI parts are hidden automatically too.
AI_ENABLED = env_bool("AI_ENABLED", True)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")       # optional: pin one model; otherwise the code tries a fallback chain
AI_CHAT_PER_HOUR = env_int("AI_CHAT_PER_HOUR", 20)
AI_CHAT_PER_DAY = env_int("AI_CHAT_PER_DAY", 60)
AI_DIAGNOSE_PER_HOUR = env_int("AI_DIAGNOSE_PER_HOUR", 5)
AI_DIAGNOSE_PER_DAY = env_int("AI_DIAGNOSE_PER_DAY", 15)
# When True, people must click the link in their verification email before they can use the AI features.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", False)

CRON_SECRET = os.getenv("CRON_SECRET", "")

# --------------------------------------------------------------------------
# Analytics dashboard, backups
# --------------------------------------------------------------------------
ANALYTICS_TIMEZONE = os.getenv("ANALYTICS_TIMEZONE", TIME_ZONE)
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", BASE_DIR / "backups"))
BACKUP_KEEP = env_int("BACKUP_KEEP", 14)

# --------------------------------------------------------------------------
# Logging + optional Sentry error tracking (set SENTRY_DSN to enable)
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, send_default_pii=False,
                        environment="development" if DEBUG else "production")
    except ImportError:  # sentry-sdk not installed: keep running
        pass
