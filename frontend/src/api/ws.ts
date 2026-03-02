import { getAccessToken } from "./http";

export type WsEvent =
  | { type: "session"; session_id: string }
  | {
    type: "meta";
    session_id?: string;
    programming_difficulty: number;
    maths_difficulty: number;
    programming_hint_level: number;
    maths_hint_level: number;
    same_problem: boolean;
    is_elaboration: boolean;
    source:
    | "single_pass_header_route"
    | "two_step_recovery_route"
    | "emergency_full_hint_fallback"
    | string;
  }
  | { type: "token"; session_id?: string; content: string }
  | {
    type: "status";
    session_id?: string;
    status: "reconnecting" | string;
    stage: string;
    attempt: number;
    max_attempts: number;
    switched_model?: boolean;
    message: string;
  }
  | {
    type: "done";
    session_id?: string;
    programming_difficulty: number;
    maths_difficulty: number;
    programming_hint_level: number;
    maths_hint_level: number;
    input_tokens: number;
    output_tokens: number;
  }
  | { type: "error"; session_id?: string; message: string };

export interface ChatSendOptions {
  sessionId?: string | null;
  uploadIds?: string[];
  notebookId?: string;
  zoneNotebookId?: string;
  cellCode?: string | null;
  errorOutput?: string | null;
}

export interface ChatSendPayload extends ChatSendOptions {
  content: string;
}

export interface ChatSocketCloseInfo {
  closedByClient: boolean;
  code: number;
  reason: string;
  wasClean: boolean;
}

export function createChatSocket(
  onEvent: (event: WsEvent) => void,
  onOpen?: () => void,
  onClose?: (info: ChatSocketCloseInfo) => void
): {
  send: (payload: ChatSendPayload) => boolean;
  isOpen: () => boolean;
  close: () => void;
} {
  const token = getAccessToken();
  if (!token) {
    onEvent({ type: "error", message: "Not authenticated" });
    return {
      send: () => false,
      isOpen: () => false,
      close: () => {},
    };
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

  ws.onclose = (event) => {
    onClose?.({
      closedByClient,
      code: event.code,
      reason: event.reason,
      wasClean: event.wasClean,
    });
  };

  const send = (payload: ChatSendPayload): boolean => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(
        JSON.stringify({
          content: payload.content,
          session_id: payload.sessionId ?? null,
          upload_ids: payload.uploadIds ?? [],
          notebook_id: payload.notebookId ?? null,
          zone_notebook_id: payload.zoneNotebookId ?? null,
          cell_code: payload.cellCode ?? null,
          error_output: payload.errorOutput ?? null,
        })
      );
      return true;
    }
    return false;
  };

  const isOpen = () => ws.readyState === WebSocket.OPEN;

  const close = () => {
    closedByClient = true;
    ws.close();
  };

  return { send, isOpen, close };
}
