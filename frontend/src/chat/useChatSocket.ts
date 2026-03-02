import { useCallback, useEffect, useRef, useState } from "react";

import { ChatMessage } from "../api/types";
import {
  ChatSendOptions,
  ChatSendPayload,
  createChatSocket,
  WsEvent,
} from "../api/ws";

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

type PendingRequestState = {
  payload: ChatSendPayload;
  terminalReceived: boolean;
  sessionAcknowledged: boolean;
  sentCount: number;
  autoResendAttempts: number;
  shouldResendOnReconnect: boolean;
};

const RECONNECT_BASE_DELAY_MS = 300;
const RECONNECT_MAX_DELAY_MS = 3000;
const MAX_AUTO_RESEND_ATTEMPTS = 1;
const NON_RECONNECTABLE_CLOSE_CODES = new Set([4001, 4002]);

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
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const connectSocketRef = useRef<(() => void) | null>(null);
  const closedByHookRef = useRef(false);
  const pendingRequestRef = useRef<PendingRequestState | null>(null);
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

  const appendSystemError = useCallback((message: string) => {
    setMessages((items) => [
      ...items,
      { role: "assistant", content: `Error: ${message}` },
    ]);
  }, []);

  const sendPendingNow = useCallback((pending: PendingRequestState): boolean => {
    const socket = socketRef.current;
    if (!socket || !socket.isOpen()) {
      return false;
    }
    if (!socket.send(pending.payload)) {
      return false;
    }
    pending.sentCount += 1;
    return true;
  }, []);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (closedByHookRef.current || reconnectTimerRef.current !== null) {
      return;
    }
    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(
      RECONNECT_MAX_DELAY_MS,
      RECONNECT_BASE_DELAY_MS * (2 ** attempt)
    );
    reconnectAttemptRef.current = attempt + 1;
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null;
      connectSocketRef.current?.();
    }, delay);
  }, []);

  const handleEvent = useCallback((event: WsEvent) => {
    const incomingSessionId = "session_id" in event ? event.session_id : undefined;
    const pending = pendingRequestRef.current;

    if (event.type === "session" && pending && !pending.terminalReceived) {
      pending.sessionAcknowledged = true;
      pending.shouldResendOnReconnect = false;
      setRetryStatus(null);
    }
    if ((event.type === "done" || event.type === "error") && pending) {
      pending.terminalReceived = true;
      pending.shouldResendOnReconnect = false;
      pendingRequestRef.current = null;
    }

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
        appendSystemError(event.message);
        setStreamingContent("");
        setStreamingMeta(null);
        setRetryStatus(null);
        setIsStreaming(false);
        break;
      case "status":
        setRetryStatus(event.message);
        break;
    }
  }, [appendSystemError, setSessionId]);

  const connectSocket = useCallback(() => {
    if (closedByHookRef.current) {
      return;
    }
    const socket = createChatSocket(
      handleEvent,
      () => {
        setConnected(true);
        reconnectAttemptRef.current = 0;
        const pending = pendingRequestRef.current;
        if (!pending || pending.terminalReceived) {
          return;
        }

        if (pending.sentCount === 0) {
          if (sendPendingNow(pending)) {
            setRetryStatus(null);
          }
          return;
        }

        if (
          pending.shouldResendOnReconnect
          && !pending.sessionAcknowledged
          && pending.autoResendAttempts < MAX_AUTO_RESEND_ATTEMPTS
        ) {
          pending.shouldResendOnReconnect = false;
          pending.autoResendAttempts += 1;
          if (sendPendingNow(pending)) {
            setRetryStatus("Connection restored. Retrying your last message.");
            return;
          }
          pending.shouldResendOnReconnect = true;
          scheduleReconnect();
        }
      },
      (info) => {
        setConnected(false);
        if (info.closedByClient || closedByHookRef.current) {
          return;
        }

        const pending = pendingRequestRef.current;
        if (pending && !pending.terminalReceived) {
          if (
            !pending.sessionAcknowledged
            && pending.autoResendAttempts < MAX_AUTO_RESEND_ATTEMPTS
          ) {
            pending.shouldResendOnReconnect = true;
            setRetryStatus(
              "Connection lost. Reconnecting and retrying your last message once."
            );
          } else if (pending.sessionAcknowledged) {
            pendingRequestRef.current = null;
            setStreamingContent("");
            setStreamingMeta(null);
            setRetryStatus(null);
            setIsStreaming(false);
            appendSystemError(
              "The connection dropped after your request started. Please send the message again."
            );
          } else {
            pendingRequestRef.current = null;
            setStreamingContent("");
            setStreamingMeta(null);
            setRetryStatus(null);
            setIsStreaming(false);
            appendSystemError(
              "The connection could not be restored automatically. Please send the message again."
            );
          }
        }

        if (NON_RECONNECTABLE_CLOSE_CODES.has(info.code)) {
          return;
        }
        scheduleReconnect();
      }
    );
    socketRef.current = socket;
  }, [appendSystemError, handleEvent, scheduleReconnect, sendPendingNow]);

  useEffect(() => {
    connectSocketRef.current = connectSocket;
  }, [connectSocket]);

  useEffect(() => {
    closedByHookRef.current = false;
    connectSocket();
    return () => {
      closedByHookRef.current = true;
      clearReconnectTimer();
      socketRef.current?.close();
    };
  }, [clearReconnectTimer, connectSocket]);

  const sendMessage = useCallback((content: string, options: ChatSendOptions = {}): boolean => {
    const existingPending = pendingRequestRef.current;
    if (existingPending && !existingPending.terminalReceived) {
      return false;
    }

    const pending: PendingRequestState = {
      payload: {
        content,
        sessionId: options.sessionId ?? null,
        uploadIds: options.uploadIds ?? [],
        notebookId: options.notebookId,
        zoneNotebookId: options.zoneNotebookId,
        cellCode: options.cellCode ?? null,
        errorOutput: options.errorOutput ?? null,
      },
      terminalReceived: false,
      sessionAcknowledged: false,
      sentCount: 0,
      autoResendAttempts: 0,
      shouldResendOnReconnect: false,
    };
    pendingRequestRef.current = pending;

    if (sendPendingNow(pending)) {
      setRetryStatus(null);
      return true;
    }

    pending.shouldResendOnReconnect = true;
    setRetryStatus("Connection lost. Reconnecting and retrying your last message once.");
    scheduleReconnect();
    return true;
  }, [scheduleReconnect, sendPendingNow]);

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
    sendMessage,
  };
}
