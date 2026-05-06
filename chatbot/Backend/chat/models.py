"""Chat models.

A single Message row holds an array of `content_blocks` whose shapes mirror
LangChain / Anthropic content blocks. This keeps the schema flat and makes
it trivial to replay a conversation back to the LLM.

Block shapes:
    {"type": "text",        "text": "..."}
    {"type": "thinking",    "text": "..."}
    {"type": "tool_use",    "id": "...", "name": "...", "input": {...}}
    {"type": "tool_result", "tool_use_id": "...", "content": [...], "is_error": bool}
    {"type": "image",       "mime_type": "image/png", "attachment_id": int}
    {"type": "file",        "mime_type": "application/pdf", "attachment_id": int}
"""

from django.conf import settings
from django.db import models


User = settings.AUTH_USER_MODEL


class UserMeta(models.Model):
    """Per-user chat preferences and encrypted secrets."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="chat_meta"
    )
    default_model = models.CharField(max_length=128, blank=True)
    default_base_url = models.URLField(blank=True)
    encrypted_secrets = models.JSONField(default=dict, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User chat meta"
        verbose_name_plural = "User chat meta"

    def __str__(self):
        return f"meta<{self.user_id}>"


class SystemPrompt(models.Model):
    """Reusable system prompt / persona."""

    name = models.CharField(max_length=128)
    content = models.TextField()
    owner = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="system_prompts",
        help_text="null = global; available to all users",
    )
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_default", "name")

    def __str__(self):
        scope = "global" if self.owner_id is None else f"u{self.owner_id}"
        return f"{self.name} [{scope}]"


class MCPServer(models.Model):
    """A registered MCP server, hot-loaded per conversation."""

    TRANSPORT_STDIO = "stdio"
    TRANSPORT_SSE = "sse"
    TRANSPORT_HTTP = "streamable_http"
    TRANSPORT_CHOICES = [
        (TRANSPORT_STDIO, "stdio"),
        (TRANSPORT_SSE, "sse"),
        (TRANSPORT_HTTP, "streamable_http"),
    ]

    name = models.CharField(max_length=128)
    transport = models.CharField(max_length=32, choices=TRANSPORT_CHOICES)
    config = models.JSONField(
        default=dict,
        help_text=(
            "stdio: {command, args, env}; "
            "sse/streamable_http: {url, headers}"
        ),
    )
    enabled = models.BooleanField(default=True)
    owner = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="mcp_servers",
        help_text="null = global",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"), name="uniq_mcp_owner_name"
            )
        ]
        ordering = ("name",)

    def __str__(self):
        scope = "global" if self.owner_id is None else f"u{self.owner_id}"
        return f"{self.name} ({self.transport}) [{scope}]"


class Tool(models.Model):
    """A DB-registered tool exposed to the agent."""

    KIND_BUILTIN = "builtin"
    KIND_HTTP = "http"
    KIND_SQL = "sql"
    KIND_CHOICES = [
        (KIND_BUILTIN, "builtin"),
        (KIND_HTTP, "http"),
        (KIND_SQL, "sql"),
    ]

    name = models.CharField(max_length=128)
    description = models.TextField()
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    config = models.JSONField(
        default=dict,
        help_text=(
            "builtin: {fn: 'current_time'}; "
            "http: {url, method, headers, body_schema}; "
            "sql: {connection, query_template, params_schema}"
        ),
    )
    enabled = models.BooleanField(default=True)
    owner = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="tools",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner", "name"), name="uniq_tool_owner_name"
            )
        ]
        ordering = ("name",)

    def __str__(self):
        scope = "global" if self.owner_id is None else f"u{self.owner_id}"
        return f"{self.name} ({self.kind}) [{scope}]"


class Conversation(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=255, blank=True)
    system_prompt = models.ForeignKey(
        SystemPrompt,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="conversations",
    )
    model_name = models.CharField(max_length=128, blank=True)
    base_url = models.URLField(blank=True)
    enabled_mcp_servers = models.ManyToManyField(
        MCPServer, blank=True, related_name="conversations"
    )
    enabled_tools = models.ManyToManyField(
        Tool, blank=True, related_name="conversations"
    )
    archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=("user", "-updated_at"))]

    def __str__(self):
        return self.title or f"conversation #{self.pk}"


class Message(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_SYSTEM = "system"
    ROLE_TOOL = "tool"
    ROLE_CHOICES = [
        (ROLE_USER, "user"),
        (ROLE_ASSISTANT, "assistant"),
        (ROLE_SYSTEM, "system"),
        (ROLE_TOOL, "tool"),
    ]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content_blocks = models.JSONField(default=list)
    finish_reason = models.CharField(max_length=32, blank=True)
    token_usage = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("conversation", "created_at"))]

    def __str__(self):
        return f"{self.role} #{self.pk}"


class Attachment(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="chat_attachments"
    )
    file = models.FileField(upload_to="chat/attachments/%Y/%m/")
    mime_type = models.CharField(max_length=128)
    size = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"attachment #{self.pk} ({self.mime_type})"
