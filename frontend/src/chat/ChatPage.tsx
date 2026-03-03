import { useState } from "react";
import { useAuth } from "../auth/useAuth";
import { ChatMessageList } from "./ChatMessageList";
import { ChatInput } from "./ChatInput";
import { ChatSidebar } from "./ChatSidebar";
import { useChatManager } from "./useChatManager";

const NARROW_CHAT_LAYOUT_MEDIA_QUERY = "(max-width: 768px)";

export function ChatPage() {
  const { user } = useAuth();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.matchMedia(NARROW_CHAT_LAYOUT_MEDIA_QUERY).matches;
  });

  const {
    sessions,
    messages,
    streamingContent,
    streamingMeta,
    retryStatus,
    isStreaming,
    connected,
    sessionId,
    handleSend,
    handleSelectSession,
    handleNewChat,
    handleDeleteSession,
  } = useChatManager({ sessionType: "general" });

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
              streamingMeta={streamingMeta}
              retryStatus={retryStatus}
            />
          )}
        </div>

        {/* Input area */}
        <ChatInput onSend={handleSend} disabled={isStreaming || !connected} />

        {/* Disclaimer */}
        <div className="text-center text-xs text-gray-400 py-1.5 bg-white border-t border-gray-100">
          AI can make mistakes. Please think critically and double-check responses.
        </div>
      </div>
    </div>
  );
}
