from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import (
    Attachment,
    Conversation,
    MCPServer,
    Message,
    SystemPrompt,
    Tool,
    UserMeta,
)
from .permissions import IsConversationOwner
from .serializers import (
    AttachmentSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    MCPServerSerializer,
    MessageSerializer,
    SystemPromptSerializer,
    ToolSerializer,
    UserMetaSerializer,
)


def _scoped(queryset, user):
    """Return rows owned by `user` or globally scoped (`owner` is null)."""
    return queryset.filter(Q(owner__isnull=True) | Q(owner=user))


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = (IsAuthenticated, IsConversationOwner)

    def get_queryset(self):
        return Conversation.objects.filter(user=self.request.user).prefetch_related(
            "enabled_mcp_servers", "enabled_tools"
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ConversationDetailSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=("get",))
    def messages(self, request, pk=None):
        conversation = self.get_object()
        qs = conversation.messages.all()
        return Response(MessageSerializer(qs, many=True).data)


class MCPServerViewSet(viewsets.ModelViewSet):
    serializer_class = MCPServerSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return _scoped(MCPServer.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class ToolViewSet(viewsets.ModelViewSet):
    serializer_class = ToolSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return _scoped(Tool.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class SystemPromptViewSet(viewsets.ModelViewSet):
    serializer_class = SystemPromptSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return _scoped(SystemPrompt.objects.all(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class UserMetaViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Singleton view: GET/PATCH /api/chat/me/meta/."""

    serializer_class = UserMetaSerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        meta, _ = UserMeta.objects.get_or_create(user=self.request.user)
        return meta

    def list(self, request):
        return self.retrieve(request)


class AttachmentViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AttachmentSerializer
    permission_classes = (IsAuthenticated, IsConversationOwner)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_queryset(self):
        return Attachment.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        f = request.FILES.get("file")
        if f is None:
            return Response(
                {"detail": "file required"}, status=status.HTTP_400_BAD_REQUEST
            )
        attachment = Attachment.objects.create(
            user=request.user,
            file=f,
            mime_type=f.content_type or "application/octet-stream",
            size=f.size,
        )
        return Response(
            AttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )
