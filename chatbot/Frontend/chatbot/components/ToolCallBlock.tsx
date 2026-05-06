import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

interface ToolCallBlockProps {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
  isError?: boolean;
  status?: "running" | "complete";
}

export function ToolCallBlock({
  name,
  args,
  result,
  isError,
  status = "complete",
}: ToolCallBlockProps) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="my-2 overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 px-3 py-2">
        <div className="flex items-center gap-2 text-sm">
          <Badge variant={isError ? "destructive" : "secondary"}>tool</Badge>
          <span className="font-mono">{name}</span>
          {status === "running" && (
            <span className="text-xs text-muted-foreground">running…</span>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide" : "Details"}
        </Button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-2 px-3 pb-3 text-xs">
          <div>
            <div className="mb-1 text-muted-foreground">Arguments</div>
            <pre className="overflow-x-auto rounded bg-muted px-2 py-1 font-mono">
              {JSON.stringify(args, null, 2)}
            </pre>
          </div>
          {result !== undefined && (
            <div>
              <div className="mb-1 text-muted-foreground">
                {isError ? "Error" : "Result"}
              </div>
              <pre className="max-h-64 overflow-auto rounded bg-muted px-2 py-1 font-mono">
                {typeof result === "string"
                  ? result
                  : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
