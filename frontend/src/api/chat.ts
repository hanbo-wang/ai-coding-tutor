import { ChatSession, ChatMessage } from "./types";
import { apiFetch } from "./http";

export const ChatAPI = {
    getSessions: async (params?: URLSearchParams) => {
        const query = params ? `?${params.toString()}` : "";
        return apiFetch<ChatSession[]>(`/api/chat/sessions${query}`);
    },

    getMessages: async (sessionId: string) => {
        return apiFetch<ChatMessage[]>(`/api/chat/sessions/${sessionId}/messages`);
    },

    deleteSession: async (sessionId: string) => {
        return apiFetch(`/api/chat/sessions/${sessionId}`, { method: "DELETE" });
    },

    getUsage: async () => {
        return apiFetch(`/api/chat/usage`);
    }
};
