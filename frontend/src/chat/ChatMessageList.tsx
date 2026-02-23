import { useEffect, useRef } from "react";
import { ChatMessage } from "../api/types";
import { ChatBubble } from "./ChatBubble";
import type { StreamingMeta } from "./useChatSocket";

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

  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, streamingContent]);

  return (
    <div ref={containerRef} className="h-full overflow-y-auto px-4 py-4">
      {messages.map((msg, index) => (
        <ChatBubble key={msg.id ?? index} message={msg} />
      ))}

      {(streamingContent || streamingMeta) && (
        <ChatBubble
          message={{
            role: "assistant",
            content: streamingContent,
            hint_level_used: streamingMeta?.hintLevel,
            problem_difficulty: streamingMeta?.programmingDifficulty,
            maths_difficulty: streamingMeta?.mathsDifficulty,
          }}
        />
      )}
    </div>
  );
}
