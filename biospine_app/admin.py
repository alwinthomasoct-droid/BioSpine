from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import ChatMessage, ContactMessage, PostureSession, Review, UserProfile


class PostureSessionInline(admin.TabularInline):
    model = PostureSession
    extra = 0
    can_delete = False
    readonly_fields = ("date", "duration_seconds", "compliance_score", "alert_count", "avg_sagittal_deviation")
    fields = readonly_fields
    ordering = ("-date",)
    max_num = 0


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at", "email_verified", "active_mode", "current_streak", "longest_streak",
                    "session_count", "height_cm", "weight_kg", "analytics_link")
    search_fields = ("email",)
    list_filter = ("email_verified", "weekly_email", "active_mode", "created_at")
    date_hierarchy = "created_at"
    # Never show the password hash or the live login token, even to admins.
    exclude = ("password_hash", "session_token")
    readonly_fields = ("created_at", "last_streak_date")
    inlines = [PostureSessionInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_n=Count("sessions"))

    @admin.display(description="Sessions", ordering="_n")
    def session_count(self, obj):
        return obj._n

    @admin.display(description="Analytics")
    def analytics_link(self, obj):
        return format_html('<a href="{}">Full timeline &rarr;</a>',
                           reverse("analytics_user", args=[obj.pk]))


@admin.register(PostureSession)
class PostureSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "duration_seconds", "compliance_score", "alert_count", "avg_sagittal_deviation")
    list_filter = ("date",)
    search_fields = ("user__email",)
    date_hierarchy = "date"
    list_select_related = ("user",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "short_question")
    search_fields = ("user__email", "question")
    date_hierarchy = "created_at"
    list_select_related = ("user",)

    @admin.display(description="Question")
    def short_question(self, obj):
        return obj.question[:80]


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "created_at", "handled")
    list_filter = ("handled", "created_at")
    search_fields = ("name", "email", "message")
    list_editable = ("handled",)
    date_hierarchy = "created_at"


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Tick 'Show on home' to publish a review on the public home page (untick to hide it again)."""
    list_display = ("created_at", "user", "rating", "display_name", "short_comment", "show_on_home")
    list_editable = ("show_on_home",)
    list_filter = ("show_on_home", "rating", "created_at")
    search_fields = ("user__email", "display_name", "comment")
    list_select_related = ("user",)
    date_hierarchy = "created_at"
    actions = ("publish_on_home", "hide_from_home")

    @admin.display(description="Comment")
    def short_comment(self, obj):
        return obj.comment[:90]

    @admin.action(description="Show the selected reviews on the home page")
    def publish_on_home(self, request, queryset):
        self.message_user(request, f"{queryset.update(show_on_home=True)} review(s) now shown on the home page.")

    @admin.action(description="Hide the selected reviews from the home page")
    def hide_from_home(self, request, queryset):
        self.message_user(request, f"{queryset.update(show_on_home=False)} review(s) hidden.")
