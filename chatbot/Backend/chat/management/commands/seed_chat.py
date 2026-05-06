"""Seed default SystemPrompt + a sample built-in tool + an example MCP server."""

from django.core.management.base import BaseCommand

from chat.models import MCPServer, SystemPrompt, Tool


DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Think step-by-step before responding when "
    "the question is non-trivial. Use the available tools when they would "
    "produce a more accurate or up-to-date answer. When you call a tool, "
    "explain why briefly."
)


class Command(BaseCommand):
    help = "Seed default chat configuration (system prompt, builtin tool, sample MCP server)."

    def handle(self, *args, **options):
        prompt, created = SystemPrompt.objects.get_or_create(
            name="default",
            owner=None,
            defaults={"content": DEFAULT_SYSTEM_PROMPT, "is_default": True},
        )
        self.stdout.write(
            f"system prompt: {'created' if created else 'exists'} ({prompt.id})"
        )

        tool, created = Tool.objects.get_or_create(
            name="current_time",
            owner=None,
            defaults={
                "description": "Returns the current UTC ISO-8601 timestamp.",
                "kind": Tool.KIND_BUILTIN,
                "config": {"fn": "current_time"},
                "enabled": True,
            },
        )
        self.stdout.write(
            f"builtin tool current_time: {'created' if created else 'exists'} ({tool.id})"
        )

        mcp, created = MCPServer.objects.get_or_create(
            name="fetch",
            owner=None,
            defaults={
                "transport": MCPServer.TRANSPORT_STDIO,
                "config": {"command": "uvx", "args": ["mcp-server-fetch"], "env": {}},
                "enabled": False,  # off by default; user enables in admin
            },
        )
        self.stdout.write(
            f"mcp server fetch: {'created' if created else 'exists'} ({mcp.id})"
        )
