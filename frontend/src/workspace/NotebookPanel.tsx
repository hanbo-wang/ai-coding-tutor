import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";

import { apiFetch, getAccessToken } from "../api/http";
import { ZoneRuntimeFile } from "../api/types";
import {
  getCurrentCell,
  getErrorOutput,
  getNotebookState,
  loadNotebook,
  WorkspaceFilePayload,
  subscribeNotebookSaveRequested,
  waitForNotebookBridgeReady,
  subscribeNotebookDirty,
} from "./notebookBridge";

export type NotebookSaveStatus = "saved" | "saving" | "unsaved" | "error";
export type WorkspaceLayoutRefreshPhase = "drag" | "settle";
export interface WorkspaceLayoutRefreshOptions {
  reason?: string;
  force?: boolean;
}

export interface NotebookCellContext {
  cellCode: string;
  errorOutput: string | null;
}

export interface NotebookPanelHandle {
  getCellContext: () => Promise<NotebookCellContext>;
  // requestLayoutRefresh is kept for backwards compatibility but is a no-op
  requestLayoutRefresh: () => void;
}

interface NotebookPanelProps {
  notebookId: string;
  mode: "personal" | "zone";
  zoneId?: string;
  reloadKey?: number;
  workspaceKey?: string;
  onSaveStatusChange?: (status: NotebookSaveStatus) => void;
  onNotebookTitleChange?: (title: string) => void;
}

const AUTO_SAVE_INTERVAL_MS = 30000;
const WORKSPACE_KERNEL_NAME = "Numerical Computing";
const LOAD_NOTEBOOK_RETRY_COUNT = 2;
const NOTEBOOK_BRIDGE_PROTOCOL_VERSION = "bridge-single-notebook-18";
const NOTEBOOK_BRIDGE_PLUGIN_ID = "guided-cursor-jupyterlite-bridge";

function isTimeoutError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return error.message.toLowerCase().includes("timed out");
}

function isBridgeReadyTimeoutError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  const text = error.message.toLowerCase();
  return (
    text.includes("notebook bridge is not ready") ||
    (text.includes("timed out") && text.includes("ping"))
  );
}

function describeNotebookBridgeFailure(
  iframe: HTMLIFrameElement,
  error: unknown
): string {
  const fallback =
    error instanceof Error ? error.message : "Failed to load notebook content.";
  if (!isBridgeReadyTimeoutError(error)) {
    return fallback;
  }

  try {
    const iframeWindow = iframe.contentWindow as
      | (Window & {
        jupyterapp?: { hasPlugin?: (id: string) => boolean };
        __guidedCursorNotebookBridge?: {
          ready?: boolean;
          startupWarnings?: string[];
        };
      })
      | null;
    const iframeDocument = iframe.contentDocument;
    if (!iframeWindow || !iframeDocument) {
      return fallback;
    }

    const app = iframeWindow.jupyterapp;
    const bridgeRuntime = iframeWindow.__guidedCursorNotebookBridge;
    const hasBridgePlugin =
      typeof app?.hasPlugin === "function"
        ? app.hasPlugin(NOTEBOOK_BRIDGE_PLUGIN_ID)
        : null;

    if (hasBridgePlugin === false) {
      return "JupyterLite loaded without the Guided Cursor bridge extension. Rebuild the JupyterLite assets with `bash scripts/build-jupyterlite.sh`, then restart the frontend.";
    }

    if (Array.isArray(bridgeRuntime?.startupWarnings) && bridgeRuntime.startupWarnings.length > 0) {
      return `JupyterLite bridge started with runtime warnings and did not become ready: ${bridgeRuntime.startupWarnings[0]}`;
    }

    if (iframeDocument.readyState !== "complete") {
      return "JupyterLite is still loading. Please retry once.";
    }

    return "Notebook bridge did not respond in time. Refresh the notebook panel. If it persists, rebuild JupyterLite assets with `bash scripts/build-jupyterlite.sh`.";
  } catch {
    return fallback;
  }
}

function withWorkspaceKernel(
  notebookJson: Record<string, unknown>
): Record<string, unknown> {
  const metadata =
    notebookJson.metadata &&
      typeof notebookJson.metadata === "object" &&
      !Array.isArray(notebookJson.metadata)
      ? (notebookJson.metadata as Record<string, unknown>)
      : {};

  const kernelspec =
    metadata.kernelspec &&
      typeof metadata.kernelspec === "object" &&
      !Array.isArray(metadata.kernelspec)
      ? (metadata.kernelspec as Record<string, unknown>)
      : {};

  return {
    ...notebookJson,
    metadata: {
      ...metadata,
      kernelspec: {
        ...kernelspec,
        name: WORKSPACE_KERNEL_NAME,
        display_name: WORKSPACE_KERNEL_NAME,
        language: "python",
      },
    },
  };
}

async function saveWithKeepalive(
  path: string,
  payload: Record<string, unknown>
): Promise<void> {
  const headers = new Headers({ "Content-Type": "application/json" });
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(path, {
    method: "PUT",
    headers,
    credentials: "include",
    keepalive: true,
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Failed to save notebook state.");
  }
}

export const NotebookPanel = forwardRef<NotebookPanelHandle, NotebookPanelProps>(
  function NotebookPanel(
    {
      notebookId,
      mode,
      zoneId,
      reloadKey = 0,
      workspaceKey,
      onSaveStatusChange,
      onNotebookTitleChange,
    },
    ref
  ) {
    const layoutContainerRef = useRef<HTMLDivElement | null>(null);
    const iframeRef = useRef<HTMLIFrameElement | null>(null);
    const dirtyRef = useRef(false);
    const savingRef = useRef(false);
    const loadedSignatureRef = useRef<string | null>(null);
    const dirtyUnsubscribeRef = useRef<(() => void) | null>(null);
    const saveRequestUnsubscribeRef = useRef<(() => void) | null>(null);
    const bridgeRecoverySignatureRef = useRef<string | null>(null);
    const iframeSessionVersionRef = useRef(`${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);

    const [isIframeLoaded, setIsIframeLoaded] = useState(false);
    const [isIframeReady, setIsIframeReady] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [saveStatus, setSaveStatus] = useState<NotebookSaveStatus>("saved");
    const [bridgeReloadNonce, setBridgeReloadNonce] = useState(0);

    const loadPath = useMemo(() => {
      if (mode === "zone") {
        return zoneId ? `/api/zones/${zoneId}/notebooks/${notebookId}` : "";
      }
      return `/api/notebooks/${notebookId}`;
    }, [mode, notebookId, zoneId]);

    const savePath = useMemo(() => {
      if (mode === "zone") {
        return zoneId
          ? `/api/zones/${zoneId}/notebooks/${notebookId}/progress`
          : "";
      }
      return `/api/notebooks/${notebookId}`;
    }, [mode, notebookId, zoneId]);

    const iframeSrc = useMemo(() => {
      const key = encodeURIComponent(workspaceKey ?? `${mode}:${zoneId ?? ""}:${notebookId}`);
      const sessionVersion = iframeSessionVersionRef.current;
      return `/jupyterlite/lab/index.html?v=${NOTEBOOK_BRIDGE_PROTOCOL_VERSION}-${sessionVersion}-${bridgeReloadNonce}&reload=${reloadKey}&wk=${key}`;
    }, [bridgeReloadNonce, mode, notebookId, reloadKey, workspaceKey, zoneId]);

    const setStatus = useCallback(
      (status: NotebookSaveStatus) => {
        setSaveStatus(status);
        onSaveStatusChange?.(status);
      },
      [onSaveStatusChange]
    );

    const requestLayoutRefresh = useCallback(() => {
      // No-Op: Layout is handled naturally by flex/CSS
    }, []);

    const performSave = useCallback(
      async (useKeepalive: boolean) => {
        const iframe = iframeRef.current;
        if (!iframe) return;
        if (!dirtyRef.current || savingRef.current) return;
        if (!savePath) return;
        // Never save before the notebook has been fully loaded — avoids overwriting
        // valid content with an empty notebook during page transitions.
        if (!loadedSignatureRef.current) return;

        savingRef.current = true;
        setStatus("saving");

        try {
          const notebookState = await getNotebookState(iframe);
          // Guard against saving an empty notebook (e.g. bridge returning stale state).
          const cells = (notebookState as { cells?: unknown }).cells;
          if (!Array.isArray(cells) || cells.length === 0) {
            savingRef.current = false;
            return;
          }
          const payload =
            mode === "zone"
              ? { notebook_state: notebookState }
              : { notebook_json: notebookState };

          if (useKeepalive) {
            await saveWithKeepalive(savePath, payload);
          } else {
            await apiFetch(savePath, {
              method: "PUT",
              body: JSON.stringify(payload),
            });
          }

          dirtyRef.current = false;
          setStatus("saved");
        } catch {
          setStatus("error");
        } finally {
          savingRef.current = false;
        }
      },
      [mode, savePath, setStatus]
    );

    useEffect(() => {
      setIsLoading(true);
      setLoadError(null);
      setIsIframeReady(false);
      dirtyRef.current = false;
      savingRef.current = false;
      setStatus("saved");
      bridgeRecoverySignatureRef.current = null;
      if (dirtyUnsubscribeRef.current) {
        dirtyUnsubscribeRef.current();
        dirtyUnsubscribeRef.current = null;
      }
      if (saveRequestUnsubscribeRef.current) {
        saveRequestUnsubscribeRef.current();
        saveRequestUnsubscribeRef.current = null;
      }
    }, [
      notebookId,
      mode,
      zoneId,
      reloadKey,
      setStatus,
      workspaceKey,
    ]);

    useEffect(() => {
      return () => {
        if (dirtyUnsubscribeRef.current) {
          dirtyUnsubscribeRef.current();
          dirtyUnsubscribeRef.current = null;
        }
        if (saveRequestUnsubscribeRef.current) {
          saveRequestUnsubscribeRef.current();
          saveRequestUnsubscribeRef.current = null;
        }
      };
    }, []);



    useEffect(() => {
      const onMessage = (event: MessageEvent<{ command?: string }>) => {
        const iframeWindow = iframeRef.current?.contentWindow;
        if (!iframeWindow || event.source !== iframeWindow) {
          return;
        }

        if (event.data?.command === "ready") {
          setIsIframeReady(true);
        }
      };

      window.addEventListener("message", onMessage);
      return () => {
        window.removeEventListener("message", onMessage);
      };
    }, [setStatus]);

    useEffect(() => {
      if (!isIframeLoaded) return;
      if (!loadPath) {
        setIsLoading(false);
        setIsIframeReady(false);
        setLoadError("Zone notebook path is missing.");
        return;
      }

      const signature = `${mode}:${zoneId ?? ""}:${notebookId}:${reloadKey}:${workspaceKey ?? ""}`;
      if (loadedSignatureRef.current === signature) {
        setIsLoading(false);
        return;
      }

      let cancelled = false;
      const iframe = iframeRef.current;
      if (!iframe) return;

      const initialiseNotebook = async () => {
        setIsLoading(true);
        setLoadError(null);
        try {
          await waitForNotebookBridgeReady(iframe);
          const detail = await apiFetch<{
            notebook_json: Record<string, unknown>;
            title?: string;
            original_filename?: string;
          }>(loadPath);
          let workspaceFiles: WorkspaceFilePayload[] = [];
          if (mode === "zone" && zoneId) {
            const runtimeFiles = await apiFetch<ZoneRuntimeFile[]>(
              `/api/zones/${zoneId}/notebooks/${notebookId}/runtime-files`
            );
            workspaceFiles = runtimeFiles.map((item) => ({
              relative_path: item.relative_path,
              content_base64: item.content_base64,
              content_type: item.content_type,
            }));
          }
          const notebookTitle =
            detail.title?.trim() ||
            detail.original_filename?.replace(/\.ipynb$/i, "").trim() ||
            "Notebook";
          onNotebookTitleChange?.(notebookTitle);
          const notebookJson = withWorkspaceKernel(detail.notebook_json);
          const notebookKey = workspaceKey ?? `${mode}:${zoneId ?? ""}:${notebookId}`;

          let lastLoadError: unknown = null;
          for (let attempt = 1; attempt <= LOAD_NOTEBOOK_RETRY_COUNT; attempt += 1) {
            try {
              await loadNotebook(
                iframe,
                notebookJson,
                workspaceFiles,
                notebookKey,
                undefined,
                notebookTitle
              );
              lastLoadError = null;
              break;
            } catch (error) {
              lastLoadError = error;
              if (attempt >= LOAD_NOTEBOOK_RETRY_COUNT || !isTimeoutError(error)) {
                break;
              }
              await waitForNotebookBridgeReady(iframe, 10000);
            }
          }

          if (lastLoadError) {
            throw lastLoadError;
          }

          if (cancelled) return;
          setIsIframeReady(true);
          loadedSignatureRef.current = signature;
          dirtyRef.current = false;
          setStatus("saved");
          if (dirtyUnsubscribeRef.current) {
            dirtyUnsubscribeRef.current();
            dirtyUnsubscribeRef.current = null;
          }
          dirtyUnsubscribeRef.current = await subscribeNotebookDirty(iframe, () => {
            dirtyRef.current = true;
            if (!savingRef.current) {
              setStatus("unsaved");
            }
          });
          if (saveRequestUnsubscribeRef.current) {
            saveRequestUnsubscribeRef.current();
            saveRequestUnsubscribeRef.current = null;
          }
          saveRequestUnsubscribeRef.current = await subscribeNotebookSaveRequested(
            iframe,
            () => {
              void performSave(false);
            }
          );
          setIsLoading(false);
        } catch (err) {
          if (cancelled) return;
          if (
            isBridgeReadyTimeoutError(err) &&
            bridgeRecoverySignatureRef.current !== signature
          ) {
            bridgeRecoverySignatureRef.current = signature;
            setIsIframeLoaded(false);
            setIsIframeReady(false);
            setLoadError(null);
            setIsLoading(true);
            setBridgeReloadNonce((value) => value + 1);
            return;
          }
          const message =
            describeNotebookBridgeFailure(iframe, err);
          setIsIframeReady(false);
          setLoadError(message);
          setIsLoading(false);
        }
      };

      void initialiseNotebook();
      return () => {
        cancelled = true;
      };
    }, [
      isIframeLoaded,
      loadPath,
      mode,
      notebookId,
      performSave,
      reloadKey,
      setStatus,
      workspaceKey,
      zoneId,
      onNotebookTitleChange,
    ]);

    useEffect(() => {
      const timer = window.setInterval(() => {
        void performSave(false);
      }, AUTO_SAVE_INTERVAL_MS);
      return () => {
        window.clearInterval(timer);
      };
    }, [performSave]);

    useEffect(() => {
      let flushed = false;
      const flushOnce = () => {
        if (flushed) return;
        flushed = true;
        void performSave(true);
      };

      const handleBeforeUnload = () => {
        flushOnce();
      };

      const handlePageHide = () => {
        flushOnce();
      };

      window.addEventListener("beforeunload", handleBeforeUnload);
      window.addEventListener("pagehide", handlePageHide);
      return () => {
        window.removeEventListener("beforeunload", handleBeforeUnload);
        window.removeEventListener("pagehide", handlePageHide);
      };
    }, [performSave]);

    useImperativeHandle(
      ref,
      () => ({
        async getCellContext() {
          const iframe = iframeRef.current;
          if (!iframe || !isIframeReady) {
            return { cellCode: "", errorOutput: null };
          }
          try {
            const [cell, errorOutput] = await Promise.all([
              getCurrentCell(iframe),
              getErrorOutput(iframe),
            ]);
            return { cellCode: cell.code, errorOutput };
          } catch {
            return { cellCode: "", errorOutput: null };
          }
        },
        requestLayoutRefresh() {
          requestLayoutRefresh();
        },
      }),
      [isIframeReady, requestLayoutRefresh]
    );

    return (
      <div
        ref={layoutContainerRef}
        className="relative h-full min-h-0 min-w-0 overflow-hidden bg-white border-r border-gray-200"
      >
        <iframe
          ref={iframeRef}
          src={iframeSrc}
          title="Notebook workspace"
          className="block h-full w-full bg-white"
          onLoad={() => setIsIframeLoaded(true)}
        />

        {isLoading && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-white/90">
            <div className="h-10 w-10 animate-spin rounded-full border-2 border-accent border-t-transparent" />
            <p className="text-sm text-gray-700">Starting Python environment...</p>
          </div>
        )}

        {loadError && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/95 px-6 text-center">
            <div>
              <p className="text-red-600 font-medium mb-2">Notebook load error</p>
              <p className="text-sm text-gray-700">{loadError}</p>
            </div>
          </div>
        )}

        <div className="absolute bottom-3 right-3 rounded-md bg-white/90 px-2 py-1 text-xs text-gray-600 shadow">
          {saveStatus === "saved" && "Saved"}
          {saveStatus === "saving" && "Saving..."}
          {saveStatus === "unsaved" && "Unsaved changes"}
          {saveStatus === "error" && "Save failed"}
        </div>
      </div>
    );
  }
);
