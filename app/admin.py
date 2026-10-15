"""The Django admin's view of the accounts: access links (invitations, and the password
resets of #231) beside the users. Adding a link mints its token and shows the link once,
in a message; the token itself is never stored or shown again."""

from django.contrib import admin, messages

from . import links
from .models import AccessLink, Profile


@admin.register(AccessLink)
class AccessLinkAdmin(admin.ModelAdmin):
    list_display = ("kind", "note", "user", "state", "uses", "uses_allowed", "expires_at", "created_by", "created_at")
    list_filter = ("kind",)
    readonly_fields = ("state", "uses", "created_by", "created_at", "revoked_at")
    fields = ("kind", "note", "user", "expires_at", "uses_allowed", "state", "uses", "created_by", "created_at", "revoked_at")
    actions = ["revoke"]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if obj is None:
            base_clean = form.clean

            def clean(self_):
                data = base_clean(self_)
                if self_.cleaned_data.get("kind") == AccessLink.RESET and not self_.cleaned_data.get("user"):
                    self_.add_error("user", "A password reset link needs the user it is for.")
                return data
            form.clean = clean
        return form

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        link, token = links.mint(obj.kind, created_by=request.user, user=obj.user,
                                 uses=obj.uses_allowed, note=obj.note)
        link.expires_at = obj.expires_at
        link.save(update_fields=["expires_at"])
        obj.pk = link.pk
        self.message_user(request, f"Link minted — copy it now, it is not shown again: {links.url_for(link.kind, token)}",
                          level=messages.WARNING)

    def response_add(self, request, obj, post_url_continue=None):
        return super().response_add(request, obj, post_url_continue)

    @admin.action(description="Revoke the selected links")
    def revoke(self, request, queryset):
        for link in queryset:
            links.revoke(link)
        self.message_user(request, f"{queryset.count()} link(s) revoked.")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "must_change_password")
