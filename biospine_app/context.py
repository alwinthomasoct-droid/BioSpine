from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL,
        "OPERATOR_NAME": settings.OPERATOR_NAME,
        "CONTACT_EMAIL": settings.CONTACT_EMAIL,
        "AI_ON": bool(settings.AI_ENABLED and settings.GEMINI_API_KEY),
    }
