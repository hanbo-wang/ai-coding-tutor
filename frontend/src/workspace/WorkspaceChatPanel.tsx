import { useMemo, useState } from "react";
import { ChatInput } from "../chat/ChatInput";
import { ChatMessageList } from "../chat/ChatMessageList";
import { useChatManager } from "../chat/useChatManager";

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
  const [historyOpen, setHistoryOpen] = useState(false);

  const {
    sessions,
    messages,
    streamingContent,
    streamingMeta,
    retryStatus,
    isStreaming,
    connected,
    sessionId,
    isLoadingSessions,
    deletingSessionId,
    handleSend,
    handleSelectSession,
    handleNewChat,
    handleDeleteSession,
  } = useChatManager({
    sessionType,
    moduleId,
    getCellContext,
  });

  const onSelectSession = (id: string) => {
    void handleSelectSession(id);
    setHistoryOpen(false);
  };

  const onNewChat = () => {
    handleNewChat();
    setHistoryOpen(false);
  };

  const historyLabel = useMemo(() => {
    if (isLoadingSessions) return "Loading history...";
    if (sessions.length === 0) return "No history";
    return `History chats (${sessions.length})`;
  }, [isLoadingSessions, sessions.length]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="relative flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2.5">
        <h2 className="text-lg font-semibold text-brand">Tutor Chat</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setHistoryOpen((prev) => !prev)}
            disabled={isLoadingSessions}
            className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {historyLabel}
          </button>
          <button
            type="button"
            onClick={onNewChat}
            disabled={isLoadingSessions}
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
                    onClick={() => onSelectSession(session.id)}
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
        disabled={isStreaming || !connected || isLoadingSessions}
      />
    </div>
  );
}
