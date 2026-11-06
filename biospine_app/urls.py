from django.urls import path
from django.views.generic import RedirectView

from . import views, views_analytics, views_pages

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicon.ico", permanent=True)),
    path("", views.index, name="index"),

    # --- JSON API (Bearer-token authenticated except register/login/forgot) ---
    path("api/auth/register", views.api_register, name="api_register"),
    path("api/auth/login", views.api_login, name="api_login"),
    path("api/auth/session", views.api_session, name="api_session"),
    path("api/auth/logout", views.api_logout, name="api_logout"),
    path("api/auth/forgot", views.api_forgot, name="api_forgot"),
    path("api/auth/resend-verification", views.api_resend_verification, name="api_resend_verification"),
    path("api/auth/change-password", views.api_change_password, name="api_change_password"),
    path("api/auth/delete", views.api_delete_account, name="api_delete_account"),
    path("api/user/export", views.api_export, name="api_export"),
    path("api/user/sync", views.api_sync_user, name="api_sync_user"),
    path("api/user/sessions", views.api_sessions, name="api_sessions"),
    path("api/user/body", views.api_user_body, name="api_user_body"),
    path("api/user/extras", views.api_user_extras, name="api_user_extras"),
    path("api/review", views.api_review, name="api_review"),
    path("api/review/dismiss", views.api_review_dismiss, name="api_review_dismiss"),
    path("api/reviews", views.api_reviews_public, name="api_reviews_public"),
    path("api/ai/diagnose", views.api_ai_diagnose, name="api_ai_diagnose"),
    path("api/ai/chat", views.api_ai_chat, name="api_ai_chat"),
    path("api/chat/history", views.api_chat_history, name="api_chat_history"),
    path("api/chat/<int:chat_id>/delete", views.api_chat_delete, name="api_chat_delete"),

    # --- Public pages ---
    path("privacy/", views_pages.privacy, name="privacy"),
    path("terms/", views_pages.terms, name="terms"),
    path("disclaimer/", views_pages.disclaimer, name="disclaimer"),
    path("contact/", views_pages.contact, name="contact"),
    path("verify-email/<str:token>/", views_pages.verify_email, name="verify_email"),
    path("reset-password/<str:token>/", views_pages.reset_password, name="reset_password"),
    path("unsubscribe/<str:token>/", views_pages.unsubscribe, name="unsubscribe"),
    path("healthz", views_pages.healthz, name="healthz"),
    path("robots.txt", views_pages.robots_txt, name="robots"),
    path("sitemap.xml", views_pages.sitemap_xml, name="sitemap"),
    path("cron/weekly-report/", views_pages.cron_weekly, name="cron_weekly"),
    path("sw.js", views_pages.service_worker, name="service_worker"),

    # --- Staff-only server-side analytics (log in at /admin/ first) ---
    path("staff/analytics/", views_analytics.dashboard, name="analytics_dashboard"),
    path("staff/analytics/user/<int:user_id>/", views_analytics.user_page, name="analytics_user"),
    path("staff/analytics/users/", views_analytics.users_page, name="analytics_users"),
    path("staff/analytics/user/<int:user_id>/session/<int:session_id>/", views_analytics.session_page, name="analytics_session"),
    path("staff/analytics/engagement/", views_analytics.engagement_page, name="analytics_engagement"),
    path("staff/analytics/posture/", views_analytics.posture_page, name="analytics_posture"),
    path("staff/analytics/time/", views_analytics.time_page, name="analytics_time"),
    path("staff/analytics/body/", views_analytics.body_page, name="analytics_body"),
    path("staff/analytics/reports/", views_analytics.reports_page, name="analytics_reports"),
    path("staff/analytics/user/<int:user_id>/report.<str:fmt>", views_analytics.report_user, name="analytics_report_user"),
    path("staff/analytics/report.<str:fmt>", views_analytics.report_platform, name="analytics_report_platform"),
    path("staff/analytics/reviews/", views_analytics.reviews_page, name="analytics_reviews"),
    path("staff/analytics/reviews/<int:review_id>/toggle", views_analytics.review_toggle, name="analytics_review_toggle"),
    path("staff/analytics/export/users.csv", views_analytics.export_users_csv, name="analytics_export_users"),
    path("staff/analytics/export/sessions.csv", views_analytics.export_sessions_csv, name="analytics_export_sessions"),
]
