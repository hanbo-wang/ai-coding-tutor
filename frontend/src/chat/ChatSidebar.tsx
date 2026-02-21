import { ChatSession } from "../api/types";

interface ChatSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onDeleteSession: (sessionId: string) => void;
}

export function ChatSidebar({
  sessions,
  activeSessionId,
  collapsed,
  onToggleCollapse,
  onSelectSession,
  onNewChat,
  onDeleteSession,
}: ChatSidebarProps) {
  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const days = Math.floor(diff / 86400000);

    if (days === 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return `${days}d ago`;
    return d.toLocaleDateString();
  };

  if (collapsed) {
    return (
      <div className="w-10 bg-white border-r border-gray-200 flex flex-col items-center pt-3">
        <button
          onClick={onToggleCollapse}
          className="text-gray-500 hover:text-brand p-1"
          title="Expand sidebar"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <div className="w-64 bg-white border-r border-gray-200 flex flex-col">
      {/* Header */}
      <div className="p-3 border-b border-gray-100 flex items-center justify-between">
        <button
          onClick={onNewChat}
          className="flex-1 bg-accent text-brand text-sm font-medium px-3 py-1.5 rounded hover:bg-accent-dark"
        >
          + New Chat
        </button>
        <button
          onClick={onToggleCollapse}
          className="ml-2 text-gray-400 hover:text-brand p-1"
          title="Collapse sidebar"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7M19 19l-7-7 7-7" />
          </svg>
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <p className="text-sm text-gray-400 text-center mt-6 px-3">
            No conversations yet
          </p>
        ) : (
          sessions.map((session) => (
            <div
              key={session.id}
              className={`group px-3 py-2.5 cursor-pointer border-b border-gray-50 hover:bg-gray-50 ${
                session.id === activeSessionId ? "bg-gray-100" : ""
              }`}
              onClick={() => onSelectSession(session.id)}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">
                    {session.preview}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {formatDate(session.created_at)}
                  </p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteSession(session.id);
                  }}
                  className="ml-2 text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity p-0.5"
                  title="Delete conversation"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
