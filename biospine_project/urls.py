from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("biospine_app.urls")),
]

handler404 = "biospine_app.views_pages.not_found"
handler500 = "biospine_app.views_pages.server_error"
