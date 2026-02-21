const COMMAND_TIMEOUT_MS = 10000;
const LOAD_NOTEBOOK_TIMEOUT_MS = 45000;
const BRIDGE_READY_TIMEOUT_MS = 20000;
const BRIDGE_READY_POLL_MS = 500;

interface BridgeEnvelope {
  command: string;
  request_id?: string;
  notebook_json?: Record<string, unknown>;
  notebook_key?: string;
  notebook_name?: string;
  notebook_title?: string;
  code?: string;
  cell_index?: number;
  error?: string | null;
  ok?: boolean;
}

function requireIframeWindow(iframe: HTMLIFrameElement): Window {
  const target = iframe.contentWindow;
  if (!target) {
    throw new Error("Notebook iframe is not ready.");
  }
  return target;
}

function createRequestId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function postCommand<T extends BridgeEnvelope>(
  iframe: HTMLIFrameElement,
  command: string,
  payload: Record<string, unknown> = {},
  timeoutMs: number = COMMAND_TIMEOUT_MS
): Promise<T> {
  const targetWindow = requireIframeWindow(iframe);
  const requestId = createRequestId();

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", onMessage);
      reject(new Error(`Notebook command timed out: ${command}`));
    }, timeoutMs);

    const onMessage = (event: MessageEvent<BridgeEnvelope>) => {
      if (event.source !== targetWindow) {
        return;
      }

      const data = event.data;
      if (!data || data.command !== command) {
        return;
      }
      if (data.request_id && data.request_id !== requestId) {
        return;
      }
      if (settled) {
        return;
      }

      settled = true;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onMessage);
      if (data.error) {
        reject(new Error(data.error));
        return;
      }
      resolve(data as T);
    };

    window.addEventListener("message", onMessage);
    targetWindow.postMessage(
      { command, request_id: requestId, ...payload },
      window.location.origin
    );
  });
}

export async function loadNotebook(
  iframe: HTMLIFrameElement,
  notebookJson: Record<string, unknown>,
  notebookKey?: string,
  notebookName?: string,
  notebookTitle?: string,
  timeoutMs: number = LOAD_NOTEBOOK_TIMEOUT_MS
): Promise<void> {
  await postCommand(iframe, "load-notebook", {
    notebook_json: notebookJson,
    notebook_key: notebookKey,
    notebook_name: notebookName,
    notebook_title: notebookTitle,
  }, timeoutMs);
}

export async function pingNotebookBridge(
  iframe: HTMLIFrameElement,
  timeoutMs: number = 3000
): Promise<void> {
  await postCommand<BridgeEnvelope>(iframe, "ping", {}, timeoutMs);
}

export async function waitForNotebookBridgeReady(
  iframe: HTMLIFrameElement,
  timeoutMs: number = BRIDGE_READY_TIMEOUT_MS
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;

  while (Date.now() < deadline) {
    const remainingMs = Math.max(300, deadline - Date.now());
    const pingTimeoutMs = Math.min(1200, remainingMs);
    try {
      await pingNotebookBridge(iframe, pingTimeoutMs);
      return;
    } catch (error) {
      lastError = error;
      await delay(BRIDGE_READY_POLL_MS);
    }
  }

  const detail =
    lastError instanceof Error ? `: ${lastError.message}` : "";
  throw new Error(`Notebook bridge is not ready${detail}`);
}

export async function getNotebookState(
  iframe: HTMLIFrameElement
): Promise<Record<string, unknown>> {
  const response = await postCommand<BridgeEnvelope>(iframe, "get-notebook-state");
  return response.notebook_json ?? {};
}

export async function getCurrentCell(
  iframe: HTMLIFrameElement
): Promise<{ code: string; cellIndex: number }> {
  const response = await postCommand<BridgeEnvelope>(iframe, "get-current-cell");
  return {
    code: response.code ?? "",
    cellIndex: response.cell_index ?? -1,
  };
}

export async function getErrorOutput(
  iframe: HTMLIFrameElement
): Promise<string | null> {
  const response = await postCommand<BridgeEnvelope>(iframe, "get-error-output");
  return response.error ?? null;
}

export async function subscribeNotebookDirty(
  iframe: HTMLIFrameElement,
  onDirty: () => void
): Promise<() => void> {
  const targetWindow = requireIframeWindow(iframe);
  const onMessage = (event: MessageEvent<BridgeEnvelope>) => {
    if (event.source !== targetWindow) {
      return;
    }
    if (event.data?.command === "notebook-dirty") {
      onDirty();
    }
  };

  window.addEventListener("message", onMessage);
  return () => {
    window.removeEventListener("message", onMessage);
  };
}

export async function subscribeNotebookSaveRequested(
  iframe: HTMLIFrameElement,
  onSaveRequested: () => void
): Promise<() => void> {
  const targetWindow = requireIframeWindow(iframe);
  const onMessage = (event: MessageEvent<BridgeEnvelope>) => {
    if (event.source !== targetWindow) {
      return;
    }
    if (event.data?.command === "notebook-save-requested") {
      onSaveRequested();
    }
  };

  window.addEventListener("message", onMessage);
  return () => {
    window.removeEventListener("message", onMessage);
  };
}
