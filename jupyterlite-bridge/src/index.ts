import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { NotebookPanel } from "@jupyterlab/notebook";

interface BridgeMessage {
  command: string;
  request_id?: string;
  notebook_json?: Record<string, unknown>;
  notebook_key?: string;
  notebook_name?: string;
  notebook_title?: string;
}

const DEFAULT_NOTEBOOK_PATH = "workspace.ipynb";
const EMPTY_NOTEBOOK: Record<string, unknown> = {
  cells: [],
  metadata: {},
  nbformat: 4,
  nbformat_minor: 5,
};

let activePanel: NotebookPanel | null = null;
let activeNotebookPath = DEFAULT_NOTEBOOK_PATH;
let activeNotebookTitle = "Notebook";
const watchedPanelIds = new Set<string>();
let isolationQueue: Promise<void> = Promise.resolve();
let restoreTimerId: number | null = null;
const WORKSPACE_STYLE_ID = "guided-cursor-workspace-style";
const CLEAR_RECENTS_COMMAND = "docmanager:clear-recents";
const SAVE_TIMEOUT_MS = 15000;
const LOCAL_AUTOSAVE_DELAY_MS = 5000;
const MANUAL_SAVE_COMMANDS = new Set([
  "docmanager:save",
  "docmanager:save-as",
  "workspace-ui:save",
  "workspace-ui:save-as",
]);
const autosaveTimerByPanelId = new Map<string, number>();
const autosaveInFlightPanelIds = new Set<string>();
const titleRenameDisabledPanelIds = new Set<string>();
const downloadPatchedPanelIds = new Set<string>();
let downloadCommandOverrideInstalled = false;

function postToParent(message: Record<string, unknown>): void {
  window.parent.postMessage(message, window.location.origin);
}

function announceReady(): void {
  postToParent({ command: "ready" });
}

function reply(
  message: BridgeMessage,
  payload: Record<string, unknown> = {}
): void {
  postToParent({
    command: message.command,
    request_id: message.request_id,
    ...payload,
  });
}

function readCurrentCellCode(panel: NotebookPanel): string {
  const activeCell = panel.content.activeCell;
  if (!activeCell) return "";

  const model = activeCell.model as {
    sharedModel?: { getSource?: () => string };
    value?: { text?: string };
  };
  if (model.sharedModel?.getSource) {
    return model.sharedModel.getSource();
  }
  if (typeof model.value?.text === "string") {
    return model.value.text;
  }
  return "";
}

function extractLastError(panel: NotebookPanel): string | null {
  const widgets = panel.content.widgets;
  for (let cellIndex = widgets.length - 1; cellIndex >= 0; cellIndex -= 1) {
    const cell = widgets[cellIndex];
    const model = cell.model as {
      outputs?: { toJSON?: () => Array<Record<string, unknown>> };
    };
    const outputs = model.outputs?.toJSON?.() ?? [];
    for (let outputIndex = outputs.length - 1; outputIndex >= 0; outputIndex -= 1) {
      const output = outputs[outputIndex];
      if (output.output_type !== "error") continue;
      const traceback = Array.isArray(output.traceback)
        ? output.traceback.join("\n")
        : "";
      const ename = typeof output.ename === "string" ? output.ename : "Error";
      const evalue = typeof output.evalue === "string" ? output.evalue : "";
      const detail = traceback.trim() || `${ename}: ${evalue}`.trim();
      return detail || "Execution error";
    }
  }
  return null;
}

function clearPanelAutosave(panelId: string): void {
  const timerId = autosaveTimerByPanelId.get(panelId);
  if (typeof timerId === "number") {
    window.clearTimeout(timerId);
    autosaveTimerByPanelId.delete(panelId);
  }
  autosaveInFlightPanelIds.delete(panelId);
}

function schedulePanelAutosave(panel: NotebookPanel): void {
  const panelId = panel.id;
  const existingTimerId = autosaveTimerByPanelId.get(panelId);
  if (typeof existingTimerId === "number") {
    window.clearTimeout(existingTimerId);
  }

  const timerId = window.setTimeout(() => {
    autosaveTimerByPanelId.delete(panelId);
    if (panel.isDisposed) {
      clearPanelAutosave(panelId);
      return;
    }
    if (autosaveInFlightPanelIds.has(panelId)) {
      schedulePanelAutosave(panel);
      return;
    }

    autosaveInFlightPanelIds.add(panelId);
    void panel.context
      .save()
      .catch(() => {
        // Best effort autosave.
      })
      .finally(() => {
        autosaveInFlightPanelIds.delete(panelId);
        if (panel.isDisposed) {
          clearPanelAutosave(panelId);
          return;
        }

        const model = panel.context.model as { dirty?: boolean };
        if (model.dirty) {
          schedulePanelAutosave(panel);
        }
      });
  }, LOCAL_AUTOSAVE_DELAY_MS);

  autosaveTimerByPanelId.set(panelId, timerId);
}

function watchPanel(panel: NotebookPanel): void {
  if (watchedPanelIds.has(panel.id)) {
    return;
  }
  watchedPanelIds.add(panel.id);

  panel.context.model.contentChanged.connect(() => {
    postToParent({ command: "notebook-dirty" });
    schedulePanelAutosave(panel);
  });

  panel.disposed.connect(() => {
    watchedPanelIds.delete(panel.id);
    clearPanelAutosave(panel.id);
    titleRenameDisabledPanelIds.delete(panel.id);
    downloadPatchedPanelIds.delete(panel.id);
    if (activePanel?.id === panel.id) {
      activePanel = null;
    }
  });
}

function setActiveNotebookPanel(panel: NotebookPanel | null): void {
  activePanel = panel;
  if (panel) {
    watchPanel(panel);
  }
}

function hashNotebookKey(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash +=
      (hash << 1) +
      (hash << 4) +
      (hash << 7) +
      (hash << 8) +
      (hash << 24);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function normaliseNotebookTitle(notebookTitle?: string): string {
  const title = notebookTitle?.trim();
  return title || "Notebook";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function findPreferredKernelSpec(
  app: JupyterFrontEnd
): { name: string; displayName: string } | null {
  const kernelspecs = app.serviceManager.kernelspecs.specs
    ?.kernelspecs as Record<
      string,
      { name?: string; display_name?: string } | undefined
    > | undefined;
  if (!kernelspecs || typeof kernelspecs !== "object") {
    return null;
  }

  const entries = Object.entries(kernelspecs).filter((entry) => Boolean(entry[1]));
  if (entries.length === 0) {
    return null;
  }

  const preferred =
    entries.find(
      ([id, spec]) => id === "Numerical Computing" || spec?.name === "Numerical Computing"
    ) ??
    entries.find(([id, spec]) => id === "python" || spec?.name === "python") ??
    entries[0];

  const [id, spec] = preferred;
  const resolvedSpec = spec ?? {};
  const name =
    typeof resolvedSpec.name === "string" && resolvedSpec.name.trim()
      ? resolvedSpec.name.trim()
      : id;
  const displayName =
    typeof resolvedSpec.display_name === "string" &&
    resolvedSpec.display_name.trim()
      ? resolvedSpec.display_name.trim()
      : name;
  return { name, displayName };
}

function withAvailableKernelMetadata(
  app: JupyterFrontEnd,
  notebookJson: Record<string, unknown>
): Record<string, unknown> {
  const kernel = findPreferredKernelSpec(app);
  if (!kernel) {
    return notebookJson;
  }

  const metadata = isRecord(notebookJson.metadata) ? notebookJson.metadata : {};
  const kernelspec = isRecord(metadata.kernelspec) ? metadata.kernelspec : {};

  return {
    ...notebookJson,
    metadata: {
      ...metadata,
      kernelspec: {
        ...kernelspec,
        name: kernel.name,
        display_name: kernel.displayName,
        language: "python",
      },
    },
  };
}

async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
  label: string
): Promise<T> {
  let timeoutId = 0;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new Error(`${label} timed out`));
    }, timeoutMs);
  });

  try {
    return await Promise.race([operation, timeout]);
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function toNotebookPath(notebookKey?: string): string {
  if (!notebookKey) {
    return DEFAULT_NOTEBOOK_PATH;
  }
  const trimmedKey = notebookKey.trim();
  if (!trimmedKey) {
    return DEFAULT_NOTEBOOK_PATH;
  }
  const safe = trimmedKey
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  if (!safe) {
    return DEFAULT_NOTEBOOK_PATH;
  }
  const pathPrefix = safe.slice(0, 96);
  const fingerprint = hashNotebookKey(trimmedKey);
  return `workspace-${pathPrefix}-${fingerprint}.ipynb`;
}

function injectWorkspaceChromeStyles(): void {
  if (document.getElementById(WORKSPACE_STYLE_ID)) {
    return;
  }
  const style = document.createElement("style");
  style.id = WORKSPACE_STYLE_ID;
  style.textContent = `
    .jp-StatusBar,
    .jp-StatusBar-Widget,
    [class*="jp-StatusBar-"] {
      display: none !important;
    }
    .jp-SideBar { display: none !important; }
    .jp-LeftStackedPanel { display: none !important; }
    .jp-RightStackedPanel { display: none !important; }
  `;
  document.head.appendChild(style);
}

function enforceWorkspaceShellMode(app: JupyterFrontEnd): void {
  const shell = app.shell as unknown as {
    mode?: string;
    collapseLeft?: () => void;
    collapseRight?: () => void;
  };
  if (typeof shell.mode === "string") {
    shell.mode = "single-document";
  }
  shell.collapseLeft?.();
  shell.collapseRight?.();
}

function isClosableWidget(candidate: unknown): candidate is { close: () => void } {
  if (!candidate || typeof candidate !== "object") {
    return false;
  }
  return typeof (candidate as { close?: unknown }).close === "function";
}

function isDisposableWidget(candidate: unknown): candidate is { dispose: () => void } {
  if (!candidate || typeof candidate !== "object") {
    return false;
  }
  return typeof (candidate as { dispose?: unknown }).dispose === "function";
}

function closeWidgetWithoutPrompt(candidate: unknown): void {
  if (isDisposableWidget(candidate)) {
    candidate.dispose();
    return;
  }
  if (isClosableWidget(candidate)) {
    candidate.close();
  }
}

function disableNotebookTitleAutoRename(panel: NotebookPanel): void {
  if (titleRenameDisabledPanelIds.has(panel.id)) {
    return;
  }

  const candidate = panel as unknown as {
    _onTitleChanged?: (sender: unknown, args: unknown) => void;
  };
  if (typeof candidate._onTitleChanged === "function") {
    const changedSignal = panel.title.changed as {
      disconnect: (
        slot: (sender: unknown, args: unknown) => void,
        thisArg?: unknown
      ) => void;
    };
    changedSignal.disconnect(candidate._onTitleChanged, panel);
  }
  titleRenameDisabledPanelIds.add(panel.id);
}

function toDownloadFilename(notebookTitle: string, notebookPath: string): string {
  const fallbackBase = notebookPath
    .split("/")
    .pop()
    ?.replace(/\.ipynb$/i, "")
    .trim() || "notebook";
  const candidate = notebookTitle.trim() || fallbackBase;
  const safeBase = candidate
    .replace(/[\\/:*?"<>|]/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\.+$/g, "");
  const base = safeBase || fallbackBase;
  return base.toLowerCase().endsWith(".ipynb") ? base : `${base}.ipynb`;
}

function currentNotebookTitleForDownload(panel: NotebookPanel): string {
  const displayed = panel.title.label;
  if (typeof displayed === "string" && displayed.trim()) {
    return displayed.trim();
  }
  return normaliseNotebookTitle(activeNotebookTitle);
}

function triggerBrowserDownload(url: string, filename: string): void {
  const element = document.createElement("a");
  element.href = url;
  element.download = filename;
  document.body.appendChild(element);
  element.click();
  document.body.removeChild(element);
}

function patchNotebookDownload(panel: NotebookPanel, app: JupyterFrontEnd): void {
  if (downloadPatchedPanelIds.has(panel.id)) {
    return;
  }

  const context = panel.context as typeof panel.context & {
    download?: () => Promise<void>;
  };
  if (typeof context.download !== "function") {
    return;
  }

  const originalDownload = context.download.bind(context);
  context.download = async () => {
    try {
      const url = await app.serviceManager.contents.getDownloadUrl(context.path);
      const filename = toDownloadFilename(
        currentNotebookTitleForDownload(panel),
        context.path
      );
      triggerBrowserDownload(url, filename);
    } catch {
      await originalDownload();
    }
  };
  downloadPatchedPanelIds.add(panel.id);
}

function applyNotebookPresentation(
  panel: NotebookPanel,
  notebookTitle: string | undefined,
  app: JupyterFrontEnd
): void {
  const title = normaliseNotebookTitle(notebookTitle);
  disableNotebookTitleAutoRename(panel);
  patchNotebookDownload(panel, app);
  panel.title.label = title;
  panel.title.caption = title;
  document.title = title;
}

function getWorkspaceNotebookPanel(app: JupyterFrontEnd): NotebookPanel | null {
  const current = app.shell.currentWidget;
  if (current instanceof NotebookPanel && current.context.path === activeNotebookPath) {
    return current;
  }
  if (activePanel && activePanel.context.path === activeNotebookPath) {
    return activePanel;
  }
  return null;
}

async function downloadWorkspaceNotebookWithTitle(app: JupyterFrontEnd): Promise<void> {
  const panel = getWorkspaceNotebookPanel(app);
  if (!panel) {
    throw new Error("No active workspace notebook available for download.");
  }

  try {
    await panel.context.save();
  } catch {
    // Best effort save before download.
  }

  const path = panel.context.path;
  const url = await app.serviceManager.contents.getDownloadUrl(path);
  const filename = toDownloadFilename(currentNotebookTitleForDownload(panel), path);
  triggerBrowserDownload(url, filename);
}

function installDownloadCommandOverride(app: JupyterFrontEnd): void {
  if (downloadCommandOverrideInstalled) {
    return;
  }

  const commandRegistry = app.commands as unknown as {
    execute: (id: string, args?: unknown) => Promise<unknown>;
  };
  const originalExecute = commandRegistry.execute.bind(app.commands);

  commandRegistry.execute = async (id: string, args?: unknown) => {
    if (id !== "docmanager:download") {
      return originalExecute(id, args);
    }

    try {
      await downloadWorkspaceNotebookWithTitle(app);
      return;
    } catch {
      return originalExecute(id, args);
    }
  };

  downloadCommandOverrideInstalled = true;
}

async function openNotebookInLab(
  app: JupyterFrontEnd,
  notebookPath: string
): Promise<void> {
  await app.commands.execute("docmanager:open", {
    path: notebookPath,
    factory: "Notebook",
  });
}

async function closeMainAreaWidgetsExcept(
  app: JupyterFrontEnd,
  notebookPath: string
): Promise<void> {
  const widgets = app.shell.widgets?.("main");
  if (!widgets) {
    return;
  }
  let kept = false;
  for (const widget of widgets) {
    const isTarget =
      widget instanceof NotebookPanel &&
      widget.context.path === notebookPath &&
      !kept;
    if (isTarget && !kept) {
      kept = true;
      continue;
    }
    closeWidgetWithoutPrompt(widget);
  }

  if (activePanel && activePanel.context.path !== notebookPath) {
    setActiveNotebookPanel(null);
  }
}

async function deleteNotebookFilesExcept(
  app: JupyterFrontEnd,
  notebookPath: string
): Promise<void> {
  try {
    const root = await app.serviceManager.contents.get("", { content: true });
    const items = Array.isArray(root.content)
      ? root.content
      : [];
    for (const item of items) {
      if (item.type !== "notebook") {
        continue;
      }
      if (!item.path || item.path === notebookPath) {
        continue;
      }
      try {
        await app.serviceManager.contents.delete(item.path);
      } catch {
        // Best effort cleanup.
      }
    }
  } catch {
    // Best effort cleanup.
  }
}

async function shutdownSessionsExcept(
  app: JupyterFrontEnd,
  notebookPath: string
): Promise<void> {
  try {
    const running = Array.from(app.serviceManager.sessions.running());
    for (const session of running) {
      if (session.path === notebookPath) {
        continue;
      }
      try {
        await app.serviceManager.sessions.shutdown(session.id);
      } catch {
        // Best effort cleanup.
      }
    }
  } catch {
    // Best effort cleanup.
  }
}

async function clearRecentDocuments(app: JupyterFrontEnd): Promise<void> {
  try {
    await app.commands.execute(CLEAR_RECENTS_COMMAND);
  } catch {
    // Best effort cleanup.
  }
}

async function enforceSingleNotebookWorkspace(
  app: JupyterFrontEnd,
  notebookPath: string,
  notebookTitle?: string
): Promise<void> {
  enforceWorkspaceShellMode(app);
  injectWorkspaceChromeStyles();
  if (activePanel && activePanel.context.path !== notebookPath) {
    try {
      await withTimeout(activePanel.context.save(), SAVE_TIMEOUT_MS, "Notebook save before switch");
    } catch {
      // Best effort save before replacing the active panel.
    }
  }
  await closeMainAreaWidgetsExcept(app, notebookPath);
  void deleteNotebookFilesExcept(app, notebookPath);
  void shutdownSessionsExcept(app, notebookPath);
  void clearRecentDocuments(app);

  const current = app.shell.currentWidget;
  if (!(current instanceof NotebookPanel) || current.context.path !== notebookPath) {
    await openNotebookInLab(app, notebookPath);
  }
  if (app.shell.currentWidget instanceof NotebookPanel) {
    setActiveNotebookPanel(app.shell.currentWidget);
    applyNotebookPresentation(
      app.shell.currentWidget,
      notebookTitle ?? activeNotebookTitle,
      app
    );
  }
}

function queueWorkspaceIsolation(
  app: JupyterFrontEnd,
  notebookPath: string,
  notebookTitle?: string
): Promise<void> {
  isolationQueue = isolationQueue
    .catch(() => {
      // Continue queue even if previous isolation failed.
    })
    .then(() => enforceSingleNotebookWorkspace(app, notebookPath, notebookTitle));
  return isolationQueue;
}

function queueWorkspaceIsolationInBackground(
  app: JupyterFrontEnd,
  notebookPath: string,
  notebookTitle?: string
): void {
  void queueWorkspaceIsolation(app, notebookPath, notebookTitle).catch(() => {
    // Best effort. The parent already receives a success reply.
  });
}

function scheduleWorkspaceRestore(
  app: JupyterFrontEnd,
  notebookPath: string,
  notebookTitle?: string
): void {
  if (restoreTimerId !== null) {
    return;
  }
  // Coalesce bursts of shell events to avoid visual flicker.
  restoreTimerId = window.setTimeout(() => {
    restoreTimerId = null;
    queueWorkspaceIsolationInBackground(app, notebookPath, notebookTitle);
  }, 80);
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: "guided-cursor-jupyterlite-bridge",
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    enforceWorkspaceShellMode(app);
    injectWorkspaceChromeStyles();
    installDownloadCommandOverride(app);
    void app.started.then(async () => {
      await clearRecentDocuments(app);
    });

    app.commands.commandExecuted.connect((_, args: { id?: unknown }) => {
      const commandId = typeof args.id === "string" ? args.id : "";
      if (!MANUAL_SAVE_COMMANDS.has(commandId)) {
        return;
      }
      postToParent({ command: "notebook-save-requested" });
    });

    if (app.shell.currentChanged) {
      app.shell.currentChanged.connect(() => {
        const widget = app.shell.currentWidget;
        if (widget instanceof NotebookPanel) {
          if (widget.context.path !== activeNotebookPath) {
            closeWidgetWithoutPrompt(widget);
            scheduleWorkspaceRestore(app, activeNotebookPath, activeNotebookTitle);
            return;
          }
          setActiveNotebookPanel(widget);
          applyNotebookPresentation(widget, activeNotebookTitle, app);
          return;
        }
        if (!widget) {
          scheduleWorkspaceRestore(app, activeNotebookPath, activeNotebookTitle);
        }
      });
    }

    window.addEventListener("message", async (event: MessageEvent<BridgeMessage>) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const message = event.data;
      if (!message || typeof message.command !== "string") {
        return;
      }

      try {
        if (message.command === "ping") {
          reply(message, { ok: true });
          announceReady();
          return;
        }

        if (message.command === "load-notebook") {
          const notebookJson = withAvailableKernelMetadata(
            app,
            message.notebook_json ?? EMPTY_NOTEBOOK
          );
          const notebookPath = toNotebookPath(message.notebook_key);
          const notebookTitle = normaliseNotebookTitle(
            message.notebook_title ?? message.notebook_name
          );
          activeNotebookPath = notebookPath;
          activeNotebookTitle = notebookTitle;

          if (activePanel?.context.path === notebookPath) {
            const model = activePanel.context.model as {
              fromJSON?: (value: Record<string, unknown>) => void;
            };
            if (model.fromJSON) {
              model.fromJSON(notebookJson);
              void activePanel.context.save();
              applyNotebookPresentation(activePanel, notebookTitle, app);
              reply(message, { notebook_json: notebookJson });
              queueWorkspaceIsolationInBackground(app, notebookPath, notebookTitle);
              return;
            }
          }

          await withTimeout(
            app.serviceManager.contents.save(notebookPath, {
              type: "notebook",
              format: "json",
              content: notebookJson,
            }),
            SAVE_TIMEOUT_MS,
            "Notebook save"
          );
          reply(message, { notebook_json: notebookJson });
          queueWorkspaceIsolationInBackground(app, notebookPath, notebookTitle);
          return;
        }

        if (message.command === "get-notebook-state") {
          let notebookJson =
            (activePanel?.context.model.toJSON() as Record<string, unknown> | undefined) ??
            EMPTY_NOTEBOOK;
          if (!activePanel) {
            const snapshot = await app.serviceManager.contents.get(activeNotebookPath, {
              content: true,
              type: "notebook",
            });
            if (snapshot.content && typeof snapshot.content === "object") {
              notebookJson = snapshot.content as Record<string, unknown>;
            }
          }
          reply(message, { notebook_json: notebookJson });
          return;
        }

        if (message.command === "get-current-cell") {
          const code = activePanel ? readCurrentCellCode(activePanel) : "";
          const cellIndex = activePanel
            ? activePanel.content.activeCellIndex
            : -1;
          reply(message, { code, cell_index: cellIndex });
          return;
        }

        if (message.command === "get-error-output") {
          const error = activePanel ? extractLastError(activePanel) : null;
          reply(message, { error });
        }
      } catch (error) {
        const text = error instanceof Error ? error.message : "Bridge command failed";
        reply(message, { error: text });
      }
    });

    // Emit ready more than once to avoid a one-off timing race on fast loads.
    announceReady();
    window.setTimeout(announceReady, 250);
    window.setTimeout(announceReady, 1000);
  },
};

export default plugin;
