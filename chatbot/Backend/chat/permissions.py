from rest_framework import permissions


class IsConversationOwner(permissions.BasePermission):
    """Only the owning user can read/modify a Conversation, Message, or Attachment."""

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "user", None) or getattr(
            getattr(obj, "conversation", None), "user", None
        )
        return owner is not None and owner == request.user
