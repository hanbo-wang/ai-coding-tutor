import { useCallback, useEffect, useRef, useState } from "react";

import { ChatMessage } from "../api/types";
import { createChatSocket, WsEvent } from "../api/ws";

/**
 * Shared WebSocket chat state and event handling.
 *
 * Manages the socket lifecycle, message list, streaming content,
 * and session ID. Both ChatPage and WorkspaceChatPanel use this hook
 * to avoid duplicating WebSocket event handling logic.
 */
export function useChatSocket(onSessionCreated?: (sessionId: string) => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<ReturnType<typeof createChatSocket> | null>(null);
  const onSessionCreatedRef = useRef(onSessionCreated);

  useEffect(() => {
    onSessionCreatedRef.current = onSessionCreated;
  }, [onSessionCreated]);

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "session":
        setSessionId((prev) => {
          if (prev !== event.session_id) {
            onSessionCreatedRef.current?.(event.session_id);
          }
          return event.session_id;
        });
        break;
      case "token":
        setStreamingContent((prev) => prev + event.content);
        break;
      case "done":
        setStreamingContent((prev) => {
          if (prev) {
            setMessages((items) => [
              ...items,
              { role: "assistant", content: prev },
            ]);
          }
          return "";
        });
        setIsStreaming(false);
        break;
      case "canned":
        setMessages((items) => [
          ...items,
          { role: "assistant", content: event.content },
        ]);
        setIsStreaming(false);
        break;
      case "error":
        setMessages((items) => [
          ...items,
          { role: "assistant", content: `Error: ${event.message}` },
        ]);
        setStreamingContent("");
        setIsStreaming(false);
        break;
    }
  }, []);

  useEffect(() => {
    const socket = createChatSocket(
      handleEvent,
      () => setConnected(true),
      () => setConnected(false)
    );
    socketRef.current = socket;
    return () => {
      socket.close();
    };
  }, [handleEvent]);

  return {
    messages,
    setMessages,
    streamingContent,
    setStreamingContent,
    isStreaming,
    setIsStreaming,
    sessionId,
    setSessionId,
    connected,
    socketRef,
  };
}
