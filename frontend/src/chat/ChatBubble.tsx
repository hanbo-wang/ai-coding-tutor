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

  const imageAttachments = useMemo(
    () => attachments.filter((item) => item.file_type === "image"),
    [attachments]
  );
  const documentAttachments = useMemo(
    () => attachments.filter((item) => item.file_type !== "image"),
    [attachments]
  );

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
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}>
      <div
        className={`max-w-[75%] rounded-lg px-4 py-3 ${
          isUser
            ? "bg-brand text-white"
            : "bg-white border border-gray-200 text-gray-800"
        }`}
      >
        {isUser ? (
          <div className="space-y-2">
            {message.content && <p className="whitespace-pre-wrap">{message.content}</p>}

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
          <div className="prose prose-sm max-w-none">
            <MarkdownRenderer content={message.content} />
          </div>
        )}
      </div>
    </div>
  );
}
