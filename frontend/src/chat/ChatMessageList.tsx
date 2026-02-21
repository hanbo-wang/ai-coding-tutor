import { useEffect, useRef } from "react";
import { ChatMessage } from "../api/types";
import { ChatBubble } from "./ChatBubble";

interface ChatMessageListProps {
  messages: ChatMessage[];
  streamingContent: string;
}

export function ChatMessageList({
  messages,
  streamingContent,
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

      {streamingContent && (
        <ChatBubble
          message={{ role: "assistant", content: streamingContent }}
        />
      )}
    </div>
  );
}
