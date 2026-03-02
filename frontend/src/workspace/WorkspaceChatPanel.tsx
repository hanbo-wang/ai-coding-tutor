import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "../api/http";
import { ChatMessage, ChatSession } from "../api/types";
import { ChatInput } from "../chat/ChatInput";
import { ChatMessageList } from "../chat/ChatMessageList";
import { prepareSendPayload } from "../chat/prepareSend";
import { useChatSocket } from "../chat/useChatSocket";

interface WorkspaceChatPanelProps {
  sessionType: "notebook" | "zone";
  moduleId: string;
  getCellContext: () => Promise<{ cellCode: string; errorOutput: string | null }>;
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString();
}

export function WorkspaceChatPanel({
  sessionType,
  moduleId,
  getCellContext,
}: WorkspaceChatPanelProps) {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [isLoadingScopedSession, setIsLoadingScopedSession] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

  const refreshScopedSessions = useCallback(async () => {
    const params = new URLSearchParams({
      session_type: sessionType,
      module_id: moduleId,
    });
    const list = await apiFetch<ChatSession[]>(
      `/api/chat/sessions?${params.toString()}`
    );
    setSessions(list);
    return list;
  }, [sessionType, moduleId]);

  const {
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
  } = useChatSocket(() => {
    void refreshScopedSessions();
  });

  const loadSessionMessages = useCallback(
    async (targetSessionId: string) => {
      const sessionMessages = await apiFetch<ChatMessage[]>(
        `/api/chat/sessions/${targetSessionId}/messages`
      );
      setSessionId(targetSessionId);
      setMessages(sessionMessages);
    },
    [setMessages, setSessionId]
  );

  useEffect(() => {
    let cancelled = false;

    setIsLoadingScopedSession(true);
    setSessionId(null);
    setMessages([]);
    setHistoryOpen(false);

    const bootstrap = async () => {
      try {
        // Load history list only; each workspace entry starts in a fresh New chat state.
        await refreshScopedSessions();
      } catch {
        if (!cancelled) {
          setSessions([]);
          setSessionId(null);
          setMessages([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingScopedSession(false);
        }
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [
    refreshScopedSessions,
    setMessages,
    setRetryStatus,
    setSessionId,
    setStreamingContent,
    setStreamingMeta,
  ]);

  const handleSend = async (content: string, files: File[]) => {
    if (!socketRef.current || isStreaming || isLoadingScopedSession) return;

    const prepared = await prepareSendPayload(content, files).catch((err) => {
      const message =
        err instanceof Error ? err.message : "Failed to upload files.";
      setMessages((items) => [
        ...items,
        { role: "assistant", content: `Error: ${message}` },
      ]);
      throw err;
    });

    setMessages((items) => [
      ...items,
      {
        role: "user",
        content: prepared.displayContent,
        attachments: prepared.attachments,
      },
    ]);
    setStreamingContent("");
    setStreamingMeta(null);
    setRetryStatus(null);
    setIsStreaming(true);

    const context = await getCellContext();
    socketRef.current.send(prepared.cleanedContent, {
      sessionId,
      uploadIds: prepared.uploadIds,
      notebookId: sessionType === "notebook" ? moduleId : undefined,
      zoneNotebookId: sessionType === "zone" ? moduleId : undefined,
      cellCode: context.cellCode || null,
      errorOutput: context.errorOutput,
    });
  };

  const handleNewChat = () => {
    if (isLoadingScopedSession) return;
    setSessionId(null);
    setMessages([]);
    setHistoryOpen(false);
  };

  const handleSelectSession = async (targetSessionId: string) => {
    if (targetSessionId === sessionId || isLoadingScopedSession) return;
    try {
      await loadSessionMessages(targetSessionId);
      setHistoryOpen(false);
    } catch {
      // Ignore stale session errors.
    }
  };

  const handleDeleteSession = async (targetSessionId: string) => {
    if (isLoadingScopedSession || deletingSessionId) return;
    try {
      setDeletingSessionId(targetSessionId);
      await apiFetch(`/api/chat/sessions/${targetSessionId}`, { method: "DELETE" });
      await refreshScopedSessions();
      if (targetSessionId === sessionId) {
        setSessionId(null);
        setMessages([]);
      }
    } catch {
      // Keep chat usable if deletion fails.
    } finally {
      setDeletingSessionId(null);
    }
  };

  const historyLabel = useMemo(() => {
    if (isLoadingScopedSession) return "Loading history...";
    if (sessions.length === 0) return "No history";
    return `History chats (${sessions.length})`;
  }, [isLoadingScopedSession, sessions.length]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="relative flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2.5">
        <h2 className="text-lg font-semibold text-brand">Tutor Chat</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistoryOpen((prev) => !prev)}
            disabled={isLoadingScopedSession}
            className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {historyLabel}
          </button>
          <button
            type="button"
            onClick={handleNewChat}
            disabled={isLoadingScopedSession}
            className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            New chat
          </button>
        </div>

        {historyOpen && (
          <div className="absolute right-4 top-12 z-30 max-h-80 w-80 overflow-y-auto rounded-md border border-gray-200 bg-white p-2 shadow-lg">
            {sessions.length === 0 ? (
              <p className="px-2 py-3 text-xs text-gray-500">No chat history yet.</p>
            ) : (
              sessions.map((session) => (
                <div
                  key={session.id}
                  className={`group mb-1 rounded-md border px-2 py-2 ${session.id === sessionId
                    ? "border-brand/30 bg-brand/5"
                    : "border-gray-100 hover:bg-gray-50"
                    }`}
                >
                  <button
                    type="button"
                    onClick={() => void handleSelectSession(session.id)}
                    className="block w-full text-left"
                  >
                    <p className="truncate text-sm text-gray-800">{session.preview}</p>
                    <p className="mt-0.5 text-xs text-gray-500">
                      {formatDate(session.created_at)}
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDeleteSession(session.id)}
                    disabled={deletingSessionId === session.id}
                    className="mt-1 text-xs text-red-600 hover:text-red-700 disabled:opacity-60"
                  >
                    {deletingSessionId === session.id ? "Deleting..." : "Delete"}
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0">
        {messages.length === 0 && !streamingContent ? (
          <div className="flex h-full items-center justify-center px-6">
            <div className="max-w-sm text-center">
              <p className="text-sm text-gray-600">
                Ask about your notebook, current cell, or errors. The tutor will
                guide you step by step.
              </p>
            </div>
          </div>
        ) : (
          <ChatMessageList
            messages={messages}
            streamingContent={streamingContent}
            streamingMeta={streamingMeta}
            retryStatus={retryStatus}
          />
        )}
      </div>

      <ChatInput
        onSend={handleSend}
        disabled={isStreaming || !connected || isLoadingScopedSession}
      />
    </div>
  );
}
