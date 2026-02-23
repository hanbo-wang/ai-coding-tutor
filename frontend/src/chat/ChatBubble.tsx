import { useEffect, useMemo, useState } from "react";

import { apiFetchBlob } from "../api/http";
import { Attachment, ChatMessage } from "../api/types";
import { MarkdownRenderer } from "../components/MarkdownRenderer";

interface ChatBubbleProps {
  message: ChatMessage;
}

const EMPTY_ATTACHMENTS: Attachment[] = [];

export function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === "user";
  const attachments = message.attachments ?? EMPTY_ATTACHMENTS;
  const [imageUrls, setImageUrls] = useState<Record<string, string>>({});
  const bubbleContainerClass = isUser ? "justify-end" : "justify-start";
  const bubbleCardClass = isUser
    ? "bg-brand text-white ring-1 ring-inset ring-white/10 shadow-sm rounded-2xl rounded-br-md"
    : "border bg-[var(--assistant-bubble-bg)] border-[color:var(--assistant-bubble-border)] text-[var(--assistant-bubble-text)] shadow-[0_8px_22px_rgba(17,24,39,0.06)] rounded-2xl rounded-bl-md";

  const imageAttachments = useMemo(
    () => attachments.filter((item) => item.file_type === "image"),
    [attachments]
  );
  const documentAttachments = useMemo(
    () => attachments.filter((item) => item.file_type !== "image"),
    [attachments]
  );
  const hasAssistantMeta =
    !isUser &&
    typeof message.hint_level_used === "number" &&
    typeof message.problem_difficulty === "number" &&
    typeof message.maths_difficulty === "number";

  useEffect(() => {
    let cancelled = false;
    const createdUrls: string[] = [];

    async function loadImages() {
      const nextUrls: Record<string, string> = {};
      for (const attachment of imageAttachments) {
        try {
          const blob = await apiFetchBlob(attachment.url);
          const objectUrl = URL.createObjectURL(blob);
          createdUrls.push(objectUrl);
          nextUrls[attachment.id] = objectUrl;
        } catch {
          // Keep rendering even if one image fails.
        }
      }

      if (cancelled) {
        createdUrls.forEach((url) => URL.revokeObjectURL(url));
        return;
      }

      setImageUrls((prev) => {
        Object.values(prev).forEach((url) => URL.revokeObjectURL(url));
        return nextUrls;
      });
    }

    if (!isUser || imageAttachments.length === 0) {
      setImageUrls((prev) => {
        Object.values(prev).forEach((url) => URL.revokeObjectURL(url));
        return {};
      });
      return;
    }

    void loadImages();
    return () => {
      cancelled = true;
      createdUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [imageAttachments, isUser]);

  const handleDocumentDownload = async (attachment: Attachment) => {
    try {
      const blob = await apiFetchBlob(attachment.url);
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = attachment.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    } catch {
      // Keep the chat flow smooth if the download fails.
    }
  };

  return (
    <div className={`mb-4 flex ${bubbleContainerClass}`}>
      <div
        className={`max-w-[88%] px-4 py-3 md:max-w-[78%] ${bubbleCardClass}`}
      >
        {isUser ? (
          <div className="space-y-2.5">
            {message.content && (
              <p className="whitespace-pre-wrap text-[0.95rem] leading-relaxed tracking-[0.01em]">
                {message.content}
              </p>
            )}

            {imageAttachments.length > 0 && (
              <div className="grid gap-2 sm:grid-cols-2">
                {imageAttachments.map((attachment) => {
                  const src = imageUrls[attachment.id];
                  return src ? (
                    <img
                      key={attachment.id}
                      src={src}
                      alt={attachment.filename}
                      className="max-h-56 w-full rounded-md object-contain bg-black/5"
                    />
                  ) : (
                    <div
                      key={attachment.id}
                      className="flex h-24 items-center justify-center rounded-md bg-black/10 text-xs"
                    >
                      Image unavailable
                    </div>
                  );
                })}
              </div>
            )}

            {documentAttachments.length > 0 && (
              <div className="space-y-1">
                {documentAttachments.map((attachment) => (
                  <button
                    key={attachment.id}
                    type="button"
                    onClick={() => void handleDocumentDownload(attachment)}
                    className="block w-full rounded border border-white/40 px-2 py-1 text-left text-sm underline hover:bg-white/10"
                  >
                    {attachment.filename}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div>
            {hasAssistantMeta && (
              <div className="mb-3 flex flex-wrap gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
                <span className="rounded-full border border-[var(--assistant-bubble-border)] bg-white/75 px-2.5 py-1 text-[var(--markdown-muted)]">
                  Hint {message.hint_level_used}
                </span>
                <span className="rounded-full border border-[var(--assistant-bubble-border)] bg-white/75 px-2.5 py-1 text-[var(--markdown-muted)]">
                  Programming {message.problem_difficulty}
                </span>
                <span className="rounded-full border border-[var(--assistant-bubble-border)] bg-white/75 px-2.5 py-1 text-[var(--markdown-muted)]">
                  Maths {message.maths_difficulty}
                </span>
              </div>
            )}
            <div className="max-w-none">
              <MarkdownRenderer content={message.content} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
