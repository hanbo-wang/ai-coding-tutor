import { useEffect, useState } from "react";

import { apiFetch } from "../api/http";
import {
  ChatMessage,
  ScopedChatSession,
} from "../api/types";
import { ChatInput } from "../chat/ChatInput";
import { ChatMessageList } from "../chat/ChatMessageList";
import { prepareSendPayload } from "../chat/prepareSend";
import { useChatSocket } from "../chat/useChatSocket";

interface WorkspaceChatPanelProps {
  sessionType: "notebook" | "zone";
  moduleId: string;
  getCellContext: () => Promise<{ cellCode: string; errorOutput: string | null }>;
}

export function WorkspaceChatPanel({
  sessionType,
  moduleId,
  getCellContext,
}: WorkspaceChatPanelProps) {
  const [isResettingSession, setIsResettingSession] = useState(false);
  const {
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
  } = useChatSocket();

  useEffect(() => {
    let cancelled = false;

    const loadScopedSession = async () => {
      try {
        const params = new URLSearchParams({
          session_type: sessionType,
          module_id: moduleId,
        });
        const existing = await apiFetch<ScopedChatSession | null>(
          `/api/chat/sessions/find?${params.toString()}`
        );
        if (!existing?.id) {
          if (!cancelled) {
            setSessionId(null);
            setMessages([]);
            setStreamingContent("");
            setStreamingMeta(null);
          }
          return;
        }
        const sessionMessages = await apiFetch<ChatMessage[]>(
          `/api/chat/sessions/${existing.id}/messages`
        );
        if (!cancelled) {
          setSessionId(existing.id);
          setMessages(sessionMessages);
          setStreamingContent("");
          setStreamingMeta(null);
        }
      } catch {
        if (!cancelled) {
          setSessionId(null);
          setMessages([]);
          setStreamingContent("");
          setStreamingMeta(null);
        }
      }
    };

    void loadScopedSession();
    return () => {
      cancelled = true;
    };
  }, [sessionType, moduleId, setSessionId, setMessages, setStreamingContent]);

  const handleSend = async (content: string, files: File[]) => {
    if (!socketRef.current || isStreaming) return;

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

  const handleNewChat = async () => {
    if (isStreaming || isResettingSession) return;

    if (!sessionId) {
      setMessages([]);
      setStreamingContent("");
      return;
    }

    const activeSessionId = sessionId;
    try {
      setIsResettingSession(true);
      await apiFetch(`/api/chat/sessions/${activeSessionId}`, {
        method: "DELETE",
      });
      setSessionId(null);
      setMessages([]);
      setStreamingContent("");
      setStreamingMeta(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to start a new chat.";
      setMessages((items) => [
        ...items,
        { role: "assistant", content: `Error: ${message}` },
      ]);
    } finally {
      setIsResettingSession(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2.5">
        <h2 className="text-lg font-semibold text-brand">Tutor Chat</h2>
        <button
          type="button"
          onClick={() => void handleNewChat()}
          disabled={isStreaming || isResettingSession}
          className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isResettingSession ? "Resetting..." : "New chat"}
        </button>
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
          />
        )}
      </div>

      <ChatInput
        onSend={handleSend}
        disabled={isStreaming || !connected || isResettingSession}
      />
    </div>
  );
}
