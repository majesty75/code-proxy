import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import {
  chatQueryKeys,
  useMcpServers,
  useUserMeta,
} from "../hooks/useConversations";
import type { ChatApi } from "../lib/api";
import type { ConversationDTO } from "../types";

interface SettingsDialogProps {
  api: ChatApi;
  conversation: ConversationDTO | null;
}

/** Settings for the active conversation: model, base_url, MCP toggles, API keys. */
export function SettingsDialog({ api, conversation }: SettingsDialogProps) {
  const qc = useQueryClient();
  const { data: meta } = useUserMeta(api);
  const { data: mcpServers = [] } = useMcpServers(api);
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    setModel(meta?.default_model ?? "");
    setBaseUrl(meta?.default_base_url ?? "");
  }, [meta]);

  const saveMeta = useMutation({
    mutationFn: () =>
      api.patchMeta({
        default_model: model,
        default_base_url: baseUrl,
        ...(apiKey ? { set_secrets: { openai_api_key: apiKey } } : {}),
      }),
    onSuccess: () => {
      setApiKey("");
      qc.invalidateQueries({ queryKey: chatQueryKeys.meta });
    },
  });

  const enabledIds = new Set(conversation?.enabled_mcp_servers ?? []);
  const toggleServer = useMutation({
    mutationFn: (serverId: number) => {
      if (!conversation) throw new Error("no active conversation");
      const next = new Set(enabledIds);
      if (next.has(serverId)) next.delete(serverId);
      else next.add(serverId);
      return api.updateConversation(conversation.id, {
        enabled_mcp_servers: Array.from(next),
      });
    },
    onSuccess: () => {
      if (conversation) {
        qc.invalidateQueries({ queryKey: chatQueryKeys.one(conversation.id) });
      }
    },
  });

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          Settings
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Chat settings</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="model">Default model</Label>
            <Input
              id="model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="qwen2.5:7b-instruct"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="base-url">OpenAI-compatible base URL</Label>
            <Input
              id="base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="http://vllm:8000/v1"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="api-key">
              API key
              {meta?.secret_keys.includes("openai_api_key") && (
                <span className="ml-2 text-xs text-muted-foreground">
                  (currently set)
                </span>
              )}
            </Label>
            <Input
              id="api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="leave blank to keep current"
            />
          </div>

          {conversation && (
            <div className="space-y-2">
              <Label>MCP servers (per-conversation)</Label>
              <ul className="space-y-1 rounded border p-2">
                {mcpServers.length === 0 && (
                  <li className="text-xs text-muted-foreground">
                    No MCP servers registered.
                  </li>
                )}
                {mcpServers.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="font-mono">{s.name}</span>
                    <Switch
                      checked={enabledIds.has(s.id)}
                      onCheckedChange={() => toggleServer.mutate(s.id)}
                    />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button onClick={() => saveMeta.mutate()} disabled={saveMeta.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
