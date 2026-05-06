import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface ThinkingBlockProps {
  text: string;
}

/** Collapsible reasoning panel rendered inline in an assistant message. */
export function ThinkingBlock({ text }: ThinkingBlockProps) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <Card className="my-2 border-dashed bg-muted/40 px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-muted-foreground">Thinking</span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide" : "Show"}
        </Button>
      </div>
      {open && (
        <pre className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-snug text-muted-foreground">
          {text}
        </pre>
      )}
    </Card>
  );
}
