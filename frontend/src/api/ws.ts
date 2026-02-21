import { getAccessToken } from "./http";

export type WsEvent =
  | { type: "session"; session_id: string }
  | { type: "token"; content: string }
  | { type: "done"; hint_level: number; programming_difficulty: number; maths_difficulty: number }
  | { type: "error"; message: string }
  | { type: "canned"; content: string; filter: string };

export interface ChatSendOptions {
  sessionId?: string | null;
  uploadIds?: string[];
  notebookId?: string;
  zoneNotebookId?: string;
  cellCode?: string | null;
  errorOutput?: string | null;
}

export function createChatSocket(
  onEvent: (event: WsEvent) => void,
  onOpen?: () => void,
  onClose?: () => void
): {
  send: (content: string, options?: ChatSendOptions) => void;
  close: () => void;
} {
  const token = getAccessToken();
  if (!token) {
    onEvent({ type: "error", message: "Not authenticated" });
    return { send: () => {}, close: () => {} };
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
  const ws = new WebSocket(wsUrl);

  let closedByClient = false;

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: "auth", token }));
    onOpen?.();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data) as WsEvent;
      onEvent(data);
    } catch {
      // Ignore malformed messages
    }
  };

  ws.onclose = () => {
    onClose?.();
  };

  ws.onerror = () => {
    // Only report errors if the socket wasn't intentionally closed
    if (!closedByClient) {
      onEvent({ type: "error", message: "WebSocket connection failed" });
    }
  };

  const send = (content: string, options: ChatSendOptions = {}) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          content,
          session_id: options.sessionId ?? null,
          upload_ids: options.uploadIds ?? [],
          notebook_id: options.notebookId ?? null,
          zone_notebook_id: options.zoneNotebookId ?? null,
          cell_code: options.cellCode ?? null,
          error_output: options.errorOutput ?? null,
        })
      );
    }
  };

  const close = () => {
    closedByClient = true;
    ws.close();
  };

  return { send, close };
}
