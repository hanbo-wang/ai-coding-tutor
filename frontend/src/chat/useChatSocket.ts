import { useCallback, useEffect, useRef, useState } from "react";

import { ChatMessage } from "../api/types";
import { createChatSocket, WsEvent } from "../api/ws";

export interface StreamingMeta {
  programmingDifficulty: number;
  mathsDifficulty: number;
  programmingHintLevel: number;
  mathsHintLevel: number;
  sameProblem?: boolean;
  isElaboration?: boolean;
  source?: string;
}

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
  const [streamingMeta, setStreamingMeta] = useState<StreamingMeta | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<ReturnType<typeof createChatSocket> | null>(null);
  const onSessionCreatedRef = useRef(onSessionCreated);
  const streamingMetaRef = useRef<StreamingMeta | null>(null);

  useEffect(() => {
    onSessionCreatedRef.current = onSessionCreated;
  }, [onSessionCreated]);

  useEffect(() => {
    streamingMetaRef.current = streamingMeta;
  }, [streamingMeta]);

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
      case "meta":
        setStreamingMeta({
          programmingDifficulty: event.programming_difficulty,
          mathsDifficulty: event.maths_difficulty,
          programmingHintLevel: event.programming_hint_level,
          mathsHintLevel: event.maths_hint_level,
          sameProblem: event.same_problem,
          isElaboration: event.is_elaboration,
          source: event.source,
        });
        break;
      case "done":
        {
          const fallbackMeta = streamingMetaRef.current;
          const programmingDifficulty = Number.isFinite(event.programming_difficulty)
            ? event.programming_difficulty
            : fallbackMeta?.programmingDifficulty;
          const mathsDifficulty = Number.isFinite(event.maths_difficulty)
            ? event.maths_difficulty
            : fallbackMeta?.mathsDifficulty;
          const programmingHintLevel = Number.isFinite(event.programming_hint_level)
            ? event.programming_hint_level
            : fallbackMeta?.programmingHintLevel;
          const mathsHintLevel = Number.isFinite(event.maths_hint_level)
            ? event.maths_hint_level
            : fallbackMeta?.mathsHintLevel;

          setStreamingContent((prev) => {
            if (prev) {
              setMessages((items) => [
                ...items,
                {
                  role: "assistant",
                  content: prev,
                  programming_difficulty: programmingDifficulty,
                  maths_difficulty: mathsDifficulty,
                  programming_hint_level_used: programmingHintLevel,
                  maths_hint_level_used: mathsHintLevel,
                },
              ]);
            }
            return "";
          });
          setStreamingMeta(null);
          setIsStreaming(false);
          break;
        }
      case "canned":
        setMessages((items) => [
          ...items,
          { role: "assistant", content: event.content },
        ]);
        setStreamingMeta(null);
        setIsStreaming(false);
        break;
      case "error":
        setMessages((items) => [
          ...items,
          { role: "assistant", content: `Error: ${event.message}` },
        ]);
        setStreamingContent("");
        setStreamingMeta(null);
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
    streamingMeta,
    setStreamingMeta,
    isStreaming,
    setIsStreaming,
    sessionId,
    setSessionId,
    connected,
    socketRef,
  };
}
