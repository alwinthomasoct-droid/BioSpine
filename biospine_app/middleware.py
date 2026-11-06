from django.conf import settings

# The public app is a single page that loads its scripts from itself plus two pinned CDN libraries.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdnjs.cloudflare.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    # ws:/wss: are needed for the optional Wi-Fi connection to the wearable
    "connect-src 'self' ws: wss: https://cdnjs.cloudflare.com",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


class SecurityHeadersMiddleware:
    """Adds a Content-Security-Policy and Permissions-Policy to the public pages.
    The Django admin and the staff analytics dashboard are left alone (they use their own inline scripts)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        path = request.path
        if not (path.startswith("/admin/") or path.startswith("/staff/")):
            response.setdefault("Content-Security-Policy", CSP)
        # bluetooth / usb / serial are what the wearable needs; everything else is switched off
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), "
                                                  "bluetooth=(self), serial=(self), usb=(self)")
        if path.startswith("/api/"):
            response.setdefault("Cache-Control", "no-store")
        return response
