from rest_framework import serializers

from . import crypto
from .models import (
    Attachment,
    Conversation,
    MCPServer,
    Message,
    SystemPrompt,
    Tool,
    UserMeta,
)


class SystemPromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemPrompt
        fields = ("id", "name", "content", "is_default", "owner")
        read_only_fields = ("owner",)


class MCPServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = MCPServer
        fields = ("id", "name", "transport", "config", "enabled", "owner")
        read_only_fields = ("owner",)


class ToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tool
        fields = ("id", "name", "description", "kind", "config", "enabled", "owner")
        read_only_fields = ("owner",)


class UserMetaSerializer(serializers.ModelSerializer):
    """Reads return masked secret names; writes accept plaintext that we encrypt."""

    secret_keys = serializers.SerializerMethodField()
    set_secrets = serializers.DictField(
        child=serializers.CharField(allow_blank=True), write_only=True, required=False
    )
    delete_secrets = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )

    class Meta:
        model = UserMeta
        fields = (
            "default_model",
            "default_base_url",
            "settings",
            "secret_keys",
            "set_secrets",
            "delete_secrets",
        )

    def get_secret_keys(self, obj) -> list[str]:
        return sorted((obj.encrypted_secrets or {}).keys())

    def update(self, instance, validated_data):
        set_secrets = validated_data.pop("set_secrets", {}) or {}
        delete_secrets = validated_data.pop("delete_secrets", []) or []
        secrets = dict(instance.encrypted_secrets or {})
        for k, v in set_secrets.items():
            if v == "":
                secrets.pop(k, None)
            else:
                secrets[k] = crypto.encrypt(v)
        for k in delete_secrets:
            secrets.pop(k, None)
        instance.encrypted_secrets = secrets
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = (
            "id",
            "role",
            "content_blocks",
            "finish_reason",
            "token_usage",
            "created_at",
        )
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    enabled_mcp_servers = serializers.PrimaryKeyRelatedField(
        many=True, queryset=MCPServer.objects.all(), required=False
    )
    enabled_tools = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Tool.objects.all(), required=False
    )

    class Meta:
        model = Conversation
        fields = (
            "id",
            "title",
            "system_prompt",
            "model_name",
            "base_url",
            "enabled_mcp_servers",
            "enabled_tools",
            "archived",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("created_at", "updated_at")


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ("messages",)


class AttachmentSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ("id", "url", "mime_type", "size", "created_at")
        read_only_fields = fields

    def get_url(self, obj) -> str:
        request = self.context.get("request")
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url
