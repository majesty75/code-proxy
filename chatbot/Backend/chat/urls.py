from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AttachmentViewSet,
    ConversationViewSet,
    MCPServerViewSet,
    SystemPromptViewSet,
    ToolViewSet,
    UserMetaViewSet,
)

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("mcp-servers", MCPServerViewSet, basename="mcp-server")
router.register("tools", ToolViewSet, basename="tool")
router.register("system-prompts", SystemPromptViewSet, basename="system-prompt")
router.register("attachments", AttachmentViewSet, basename="attachment")
router.register("me/meta", UserMetaViewSet, basename="user-meta")

app_name = "chat"

urlpatterns = [
    path("", include(router.urls)),
]
