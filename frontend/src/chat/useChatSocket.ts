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

type StreamState = {
  content: string;
  meta: StreamingMeta | null;
  retryStatus: string | null;
};

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
  const [retryStatus, setRetryStatus] = useState<string | null>(null);
  const [sessionId, setSessionIdState] = useState<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<ReturnType<typeof createChatSocket> | null>(null);
  const onSessionCreatedRef = useRef(onSessionCreated);
  const streamingMetaRef = useRef<StreamingMeta | null>(null);
  const backgroundStreamsRef = useRef<Record<string, StreamState>>({});

  const setSessionId = useCallback((id: string | null | ((prev: string | null) => string | null)) => {
    setSessionIdState((prev) => {
      const nextId = typeof id === "function" ? id(prev) : id;
      sessionIdRef.current = nextId;

      // Swap to the background stream buffer seamlessly
      if (nextId && backgroundStreamsRef.current[nextId]) {
        const stream = backgroundStreamsRef.current[nextId];
        setStreamingContent(stream.content);
        setStreamingMeta(stream.meta);
        setRetryStatus(stream.retryStatus);
        setIsStreaming(true);
      } else {
        setStreamingContent("");
        setStreamingMeta(null);
        setRetryStatus(null);
        setIsStreaming(false);
      }

      return nextId;
    });
  }, []);

  useEffect(() => {
    onSessionCreatedRef.current = onSessionCreated;
  }, [onSessionCreated]);

  useEffect(() => {
    streamingMetaRef.current = streamingMeta;
  }, [streamingMeta]);

  const handleEvent = useCallback((event: WsEvent) => {
    const incomingSessionId = "session_id" in event ? event.session_id : undefined;

    // 1. Maintain a resilient background buffer for all active streams
    if (incomingSessionId) {
      if (!backgroundStreamsRef.current[incomingSessionId]) {
        backgroundStreamsRef.current[incomingSessionId] = { content: "", meta: null, retryStatus: null };
      }
      const stream = backgroundStreamsRef.current[incomingSessionId];

      if (event.type === "token") {
        stream.content += event.content;
      } else if (event.type === "meta") {
        stream.meta = {
          programmingDifficulty: event.programming_difficulty,
          mathsDifficulty: event.maths_difficulty,
          programmingHintLevel: event.programming_hint_level,
          mathsHintLevel: event.maths_hint_level,
          sameProblem: event.same_problem,
          isElaboration: event.is_elaboration,
          source: event.source,
        };
      } else if (event.type === "status") {
        stream.retryStatus = event.message;
      } else if (event.type === "done" || event.type === "error") {
        // Safe to clear: loading next from history will fetch completely from DB
        delete backgroundStreamsRef.current[incomingSessionId];
      }
    }

    // 2. Safely prevent active UI state blocks from mixing
    if (
      event.type !== "session" &&
      incomingSessionId &&
      incomingSessionId !== sessionIdRef.current
    ) {
      // Do nothing to the foreground UI if it's not the active session.
      return;
    }

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
        setRetryStatus(null);
        setStreamingContent((prev) => prev + event.content);
        break;
      case "meta":
        setRetryStatus(null);
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
          setRetryStatus(null);
          setIsStreaming(false);
          break;
        }
      case "error":
        setMessages((items) => [
          ...items,
          { role: "assistant", content: `Error: ${event.message}` },
        ]);
        setStreamingContent("");
        setStreamingMeta(null);
        setRetryStatus(null);
        setIsStreaming(false);
        break;
      case "status":
        setRetryStatus(event.message);
        break;
    }
  }, [setSessionId]);

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
    retryStatus,
    setRetryStatus,
    isStreaming,
    setIsStreaming,
    sessionId,
    setSessionId,
    connected,
    socketRef,
  };
}
