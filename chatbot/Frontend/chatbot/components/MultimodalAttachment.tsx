import { useRef } from "react";

import { Button } from "@/components/ui/button";

import type { ChatApi } from "../lib/api";
import type { AttachmentDTO, ContentBlock } from "../types";

interface MultimodalAttachmentProps {
  api: ChatApi;
  onAttached: (block: ContentBlock) => void;
}

/** Lightweight attachment picker; integrators can swap for assistant-ui's
 *  AttachmentPrimitive when they want drag/drop.  */
export function MultimodalAttachment({
  api,
  onAttached,
}: MultimodalAttachmentProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const onChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const uploaded: AttachmentDTO = await api.uploadAttachment(file);
    const block: ContentBlock = uploaded.mime_type.startsWith("image/")
      ? {
          type: "image",
          mime_type: uploaded.mime_type,
          attachment_id: uploaded.id,
          url: uploaded.url,
        }
      : {
          type: "file",
          mime_type: uploaded.mime_type,
          attachment_id: uploaded.id,
          url: uploaded.url,
        };
    onAttached(block);
    e.target.value = "";
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept="image/*,application/pdf,.txt,.md,.csv,.json"
        onChange={onChange}
      />
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => inputRef.current?.click()}
      >
        Attach
      </Button>
    </>
  );
}
