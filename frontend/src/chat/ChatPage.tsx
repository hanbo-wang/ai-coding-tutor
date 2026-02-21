import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../api/http";
import { ChatMessage, ChatSession } from "../api/types";
import { useAuth } from "../auth/useAuth";
import { prepareSendPayload } from "./prepareSend";
import { ChatMessageList } from "./ChatMessageList";
import { ChatInput } from "./ChatInput";
import { ChatSidebar } from "./ChatSidebar";
import { useChatSocket } from "./useChatSocket";

export function ChatPage() {
  const { user } = useAuth();

  // Sidebar state
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const handleSessionCreated = useCallback(() => {
    apiFetch<ChatSession[]>("/api/chat/sessions")
      .then(setSessions)
      .catch(() => {});
  }, []);

  const {
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
  } = useChatSocket(handleSessionCreated);

  // Load sessions on mount
  useEffect(() => {
    apiFetch<ChatSession[]>("/api/chat/sessions")
      .then(setSessions)
      .catch(() => {});
  }, []);

  const handleSend = async (content: string, files: File[]) => {
    if (!socketRef.current || isStreaming) return;

    const prepared = await prepareSendPayload(content, files).catch((err) => {
      const message =
        err instanceof Error ? err.message : "Failed to upload files.";
      setMessages((msgs) => [
        ...msgs,
        { role: "assistant", content: `Error: ${message}` },
      ]);
      throw err;
    });

    setMessages((msgs) => [
      ...msgs,
      {
        role: "user",
        content: prepared.displayContent,
        attachments: prepared.attachments,
      },
    ]);
    setStreamingContent("");
    setIsStreaming(true);
    socketRef.current.send(prepared.cleanedContent, {
      sessionId,
      uploadIds: prepared.uploadIds,
    });
  };

  const handleSelectSession = async (id: string) => {
    if (id === sessionId) return;
    try {
      const msgs = await apiFetch<ChatMessage[]>(
        `/api/chat/sessions/${id}/messages`
      );
      setMessages(msgs);
      setSessionId(id);
      setStreamingContent("");
    } catch {
      // Session may have been deleted
    }
  };

  const handleNewChat = () => {
    setSessionId(null);
    setMessages([]);
    setStreamingContent("");
  };

  const handleDeleteSession = async (id: string) => {
    try {
      await apiFetch(`/api/chat/sessions/${id}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (id === sessionId) {
        setSessionId(null);
        setMessages([]);
        setStreamingContent("");
      }
    } catch {
      // Ignore errors
    }
  };

  const greeting = user
    ? `Hello ${user.username}, I'm your AI tutor. Ask a question on programming, maths, or physics, and I'll help you step by step.`
    : "Hello, I'm your AI tutor. Ask a question on programming, maths, or physics, and I'll help you step by step.";

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <ChatSidebar
        sessions={sessions}
        activeSessionId={sessionId}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((c) => !c)}
        onSelectSession={handleSelectSession}
        onNewChat={handleNewChat}
        onDeleteSession={handleDeleteSession}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Messages area */}
        <div className="flex-1 overflow-hidden flex flex-col min-h-0 bg-gray-50">
          {messages.length === 0 && !streamingContent ? (
            <div className="flex-1 flex items-center justify-center px-4">
              <div className="text-center max-w-md">
                <h2 className="text-2xl font-bold text-brand mb-3">
                  Guided Cursor
                </h2>
                <p className="text-gray-600">{greeting}</p>
              </div>
            </div>
          ) : (
            <ChatMessageList
              messages={messages}
              streamingContent={streamingContent}
            />
          )}
        </div>

        {/* Input area */}
        <ChatInput onSend={handleSend} disabled={isStreaming || !connected} />

        {/* Disclaimer */}
        <div className="text-center text-xs text-gray-400 py-1.5 bg-white border-t border-gray-100">
          AI responses may contain errors. Always verify important information independently.
        </div>
      </div>
    </div>
  );
}
