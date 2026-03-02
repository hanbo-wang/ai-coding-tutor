import { useEffect, useRef } from "react";
import { ChatMessage } from "../api/types";
import { ChatBubble } from "./ChatBubble";
import type { StreamingMeta } from "./useChatSocket";

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 96;

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent: string;
  streamingMeta?: StreamingMeta | null;
  retryStatus?: string | null;
}

export function ChatMessageList({
  messages,
  streamingContent,
  streamingMeta,
  retryStatus,
}: ChatMessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);

  function isNearBottom(el: HTMLDivElement): boolean {
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    return distanceToBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
  }

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) {
      return;
    }

    // Only follow streaming output while the user stays near the bottom.
    shouldStickToBottomRef.current = isNearBottom(el);
  };

  useEffect(() => {
    const el = containerRef.current;
    if (el && shouldStickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
      shouldStickToBottomRef.current = true;
    }
  }, [messages, streamingContent, streamingMeta]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="h-full overflow-y-auto px-4 py-4"
      style={{ overflowAnchor: "none" }}
    >
      {messages.map((msg, index) => (
        <ChatBubble key={msg.id ?? index} message={msg} />
      ))}

      {retryStatus && (
        <div className="mb-3 flex justify-end">
          <div className="w-full max-w-[88%] rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 md:max-w-[78%]">
            {retryStatus}
          </div>
        </div>
      )}

      {(streamingContent || streamingMeta) && (
        <ChatBubble
          message={{
            role: "assistant",
            content: streamingContent,
            programming_difficulty: streamingMeta?.programmingDifficulty,
            maths_difficulty: streamingMeta?.mathsDifficulty,
            programming_hint_level_used: streamingMeta?.programmingHintLevel,
            maths_hint_level_used: streamingMeta?.mathsHintLevel,
          }}
        />
      )}
    </div>
  );
}
