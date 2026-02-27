import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "../api/types";
import { ChatBubble } from "./ChatBubble";
import type { StreamingMeta } from "./useChatSocket";

const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 160;

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent: string;
  streamingMeta?: StreamingMeta | null;
}

export function ChatMessageList({
  messages,
  streamingContent,
  streamingMeta,
}: ChatMessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldStickToBottomRef = useRef(true);
  const [containerWidth, setContainerWidth] = useState(0);

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
    if (!el) {
      return;
    }

    let frameId = 0;
    const syncWidth = () => {
      const nextWidth = Math.round(el.clientWidth);
      setContainerWidth((prev) => (prev === nextWidth ? prev : nextWidth));
    };

    syncWidth();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      frameId = requestAnimationFrame(syncWidth);
    });

    observer.observe(el);

    return () => {
      if (frameId) {
        cancelAnimationFrame(frameId);
      }
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (el && shouldStickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
      shouldStickToBottomRef.current = true;
    }
  }, [messages, streamingContent, streamingMeta, containerWidth]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="h-full overflow-y-auto px-4 py-4"
    >
      {messages.map((msg, index) => (
        <ChatBubble key={msg.id ?? index} message={msg} />
      ))}

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
