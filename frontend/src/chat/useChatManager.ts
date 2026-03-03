import { useCallback, useEffect, useState } from "react";
import { ChatAPI } from "../api/chat";
import { ChatMessage, ChatSession } from "../api/types";
import { prepareSendPayload } from "./prepareSend";
import { useChatSocket } from "./useChatSocket";

export interface UseChatManagerProps {
    sessionType?: "general" | "notebook" | "zone";
    moduleId?: string;
    getCellContext?: () => Promise<{ cellCode: string; errorOutput: string | null }>;
}

export function useChatManager(props?: UseChatManagerProps) {
    const sessionType = props?.sessionType || "general";
    const moduleId = props?.moduleId;
    const getCellContext = props?.getCellContext;

    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [isLoadingSessions, setIsLoadingSessions] = useState(false);
    const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);

    const refreshSessions = useCallback(async () => {
        const params = new URLSearchParams();
        if (sessionType !== "general") {
            params.append("session_type", sessionType);
            if (moduleId) {
                params.append("module_id", moduleId);
            }
        }
        const list = await ChatAPI.getSessions(params);
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
        sendMessage,
        consumeFreshSessionRequirement,
    } = useChatSocket(() => {
        void refreshSessions();
    });

    useEffect(() => {
        let cancelled = false;
        setIsLoadingSessions(true);
        setSessionId(null);
        setMessages([]);

        const bootstrap = async () => {
            try {
                await refreshSessions();
            } catch {
                if (!cancelled) {
                    setSessions([]);
                }
            } finally {
                if (!cancelled) {
                    setIsLoadingSessions(false);
                }
            }
        };
        void bootstrap();
        return () => {
            cancelled = true;
        };
    }, [refreshSessions, setMessages, setSessionId]);

    const handleSend = async (content: string, files: File[]) => {
        if (isStreaming || isLoadingSessions) return;

        const shouldRefreshSession = consumeFreshSessionRequirement();
        if (shouldRefreshSession) {
            setSessionId(null);
            setMessages([]);
            setRetryStatus("Chat context refreshed automatically. Sending your message again.");
        }

        const prepared = await prepareSendPayload(content, files).catch((err) => {
            const message = err instanceof Error ? err.message : "Failed to upload files.";
            setMessages((items: ChatMessage[]) => [...items, { role: "assistant", content: `Error: ${message}` }]);
            throw err;
        });

        setMessages((items: ChatMessage[]) => [
            ...items,
            { role: "user", content: prepared.displayContent, attachments: prepared.attachments },
        ]);
        setStreamingContent("");
        setStreamingMeta(null);
        setRetryStatus(null);
        setIsStreaming(true);

        let cellCode: string | null = null;
        let errorOutput: string | null = null;
        if (getCellContext) {
            const context = await getCellContext();
            cellCode = context.cellCode || null;
            errorOutput = context.errorOutput;
        }

        const accepted = sendMessage(prepared.cleanedContent, {
            sessionId: shouldRefreshSession ? null : sessionId,
            uploadIds: prepared.uploadIds,
            notebookId: sessionType === "notebook" ? moduleId : undefined,
            zoneNotebookId: sessionType === "zone" ? moduleId : undefined,
            cellCode,
            errorOutput,
        });

        if (!accepted) {
            setIsStreaming(false);
            setMessages((items: ChatMessage[]) => [
                ...items,
                { role: "assistant", content: "Error: Please wait for the current request to finish." },
            ]);
        }
    };

    const handleSelectSession = async (targetSessionId: string) => {
        if (targetSessionId === sessionId || isLoadingSessions) return;
        try {
            const sessionMessages = await ChatAPI.getMessages(targetSessionId);
            setSessionId(targetSessionId);
            setMessages(sessionMessages);
        } catch {
            // Ignore stale session errors
        }
    };

    const handleNewChat = () => {
        if (isLoadingSessions) return;
        setSessionId(null);
        setMessages([]);
    };

    const handleDeleteSession = async (targetSessionId: string) => {
        if (isLoadingSessions || deletingSessionId) return;
        try {
            setDeletingSessionId(targetSessionId);
            await ChatAPI.deleteSession(targetSessionId);
            await refreshSessions();
            if (targetSessionId === sessionId) {
                setSessionId(null);
                setMessages([]);
            }
        } catch {
            // Keep chat usable if deletion fails
        } finally {
            setDeletingSessionId(null);
        }
    };

    return {
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
    };
}
