from django.contrib import admin

from .models import (
    Attachment,
    Conversation,
    MCPServer,
    Message,
    SystemPrompt,
    Tool,
    UserMeta,
)


@admin.register(UserMeta)
class UserMetaAdmin(admin.ModelAdmin):
    list_display = ("user", "default_model", "default_base_url", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SystemPrompt)
class SystemPromptAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_default", "updated_at")
    list_filter = ("is_default",)
    search_fields = ("name", "content")


@admin.register(MCPServer)
class MCPServerAdmin(admin.ModelAdmin):
    list_display = ("name", "transport", "owner", "enabled", "updated_at")
    list_filter = ("transport", "enabled")
    search_fields = ("name",)


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner", "enabled", "updated_at")
    list_filter = ("kind", "enabled")
    search_fields = ("name", "description")


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("role", "finish_reason", "created_at")
    readonly_fields = ("role", "finish_reason", "created_at")
    show_change_link = True


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "model_name", "archived", "updated_at")
    list_filter = ("archived",)
    search_fields = ("title", "user__username")
    inlines = (MessageInline,)
    filter_horizontal = ("enabled_mcp_servers", "enabled_tools")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "role", "finish_reason", "created_at")
    list_filter = ("role",)
    readonly_fields = ("created_at",)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "mime_type", "size", "created_at")
    list_filter = ("mime_type",)
    search_fields = ("user__username",)
