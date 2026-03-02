import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { NotebookPanel } from "@jupyterlab/notebook";

interface BridgeMessage {
  command: string;
  request_id?: string;
  notebook_json?: Record<string, unknown>;
  workspace_files?: WorkspaceFilePayload[];
  notebook_key?: string;
  notebook_name?: string;
  notebook_title?: string;
  phase?: "drag" | "settle";
  reason?: "split-drag" | "split-settle" | "window-resize" | "observer-settle";
  final_pass?: boolean;
  pane_width?: number;
  pane_height?: number;
  request_ts?: number;
}

interface WorkspaceFilePayload {
  relative_path?: string;
  content_base64?: string;
  content_type?: string | null;
}

interface KernelRuntimeFile {
  path: string;
  contentBase64: string;
}

interface LayoutRefreshTarget {
  update?: () => void;
  fit?: () => void;
  node?: Element | null;
}

type LayoutRefreshPhase = "drag" | "settle";
type LayoutRefreshReason =
  | "split-drag"
  | "split-settle"
  | "window-resize"
  | "observer-settle";
type WorkspacePaneMode = "wide" | "compact";

interface LayoutRefreshRequest {
  phase: LayoutRefreshPhase;
  reason: LayoutRefreshReason;
  paneWidth: number;
  paneHeight: number;
  requestTs: number;
}

interface ScrollHostCandidate {
  label: string;
  node: HTMLElement | null;
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
const WORKSPACE_NOTEBOOK_SCOPE_CLASS = "gc-workspace-notebook";
const WORKSPACE_NOTEBOOK_COMPACT_CLASS = "gc-workspace-compact";
const WORKSPACE_SCROLL_HOST_CLASS = "gc-workspace-scroll-host";
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
const injectedRuntimePaths = new Set<string>();
const outputNormalisationInFlightPanelIds = new Set<string>();
let pendingKernelImportPaths: string[] = ["/drive"];
let pendingKernelRuntimeFiles: KernelRuntimeFile[] = [];
let runtimeSyncToken = 0;
const syncedPanelTokenById = new Map<string, number>();
let downloadCommandOverrideInstalled = false;

function postToParent(message: Record<string, unknown>): void {
  window.parent.postMessage(message, window.location.origin);
}

function markBridgeRuntime(partial: Record<string, unknown>): void {
  const runtimeWindow = window as unknown as Record<string, unknown>;
  const existing =
    runtimeWindow.__guidedCursorNotebookBridge &&
      typeof runtimeWindow.__guidedCursorNotebookBridge === "object"
      ? (runtimeWindow.__guidedCursorNotebookBridge as Record<string, unknown>)
      : {};
  runtimeWindow.__guidedCursorNotebookBridge = {
    ...existing,
    ...partial,
  };
}

function announceReady(): void {
  markBridgeRuntime({ ready: true, readyAt: Date.now() });
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
    normalisePanelOutputs(panel);
    postToParent({ command: "notebook-dirty" });
    schedulePanelAutosave(panel);
  });

  panel.sessionContext.kernelChanged.connect(() => {
    syncedPanelTokenById.delete(panel.id);
    if (panel.context.path !== activeNotebookPath) {
      return;
    }
    const syncedToken = syncedPanelTokenById.get(panel.id);
    if (syncedToken === runtimeSyncToken) {
      return;
    }
    syncedPanelTokenById.set(panel.id, runtimeSyncToken);
    void syncKernelRuntime(
      panel,
      pendingKernelImportPaths,
      pendingKernelRuntimeFiles
    );
  });

  panel.disposed.connect(() => {
    watchedPanelIds.delete(panel.id);
    clearPanelAutosave(panel.id);
    titleRenameDisabledPanelIds.delete(panel.id);
    downloadPatchedPanelIds.delete(panel.id);
    syncedPanelTokenById.delete(panel.id);
    if (activePanel?.id === panel.id) {
      activePanel = null;
    }
  });
}

function setActiveNotebookPanel(panel: NotebookPanel | null): void {
  activePanel = panel;
  if (panel) {
    watchPanel(panel);
    normalisePanelOutputs(panel);
    if (panel.context.path === activeNotebookPath) {
      const syncedToken = syncedPanelTokenById.get(panel.id);
      if (syncedToken !== runtimeSyncToken) {
        syncedPanelTokenById.set(panel.id, runtimeSyncToken);
        void syncKernelRuntime(
          panel,
          pendingKernelImportPaths,
          pendingKernelRuntimeFiles
        );
      }
    }
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

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isTextPrimitive(value: unknown): value is string | number | boolean | null {
  return (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean" ||
    value === null
  );
}

function normaliseOutputTextField(value: unknown): unknown {
  if (isStringArray(value)) {
    return value.join("");
  }
  if (Array.isArray(value) && value.every((item) => isTextPrimitive(item))) {
    return value.map((item) => (item === null ? "" : String(item))).join("");
  }
  return value;
}

function normaliseOutputTracebackField(value: unknown): unknown {
  if (isStringArray(value)) {
    // Keep traceback as one string to avoid comma insertion from Array#toString.
    return value.join("\n");
  }
  return value;
}

function normaliseNotebookOutput(
  output: Record<string, unknown>
): Record<string, unknown> {
  let changed = false;
  let nextOutput = output;
  const outputType =
    typeof output.output_type === "string" ? output.output_type : "";

  if ("text" in output) {
    const normalisedText = normaliseOutputTextField(output.text);
    if (normalisedText !== output.text) {
      nextOutput = { ...nextOutput, text: normalisedText };
      changed = true;
    }
  }

  if (
    (outputType === "display_data" || outputType === "execute_result") &&
    isRecord(output.data)
  ) {
    let dataChanged = false;
    const nextData = { ...output.data };
    for (const [mimeType, mimeValue] of Object.entries(output.data)) {
      if (!mimeType.startsWith("text/")) {
        continue;
      }
      const normalisedMimeValue = normaliseOutputTextField(mimeValue);
      if (normalisedMimeValue !== mimeValue) {
        nextData[mimeType] = normalisedMimeValue;
        dataChanged = true;
      }
    }
    if (dataChanged) {
      nextOutput = {
        ...nextOutput,
        data: nextData,
      };
      changed = true;
    }
  }

  if (outputType === "error" && "traceback" in output) {
    const normalisedTraceback = normaliseOutputTracebackField(output.traceback);
    if (normalisedTraceback !== output.traceback) {
      nextOutput = { ...nextOutput, traceback: normalisedTraceback };
      changed = true;
    }
  }

  return changed ? nextOutput : output;
}

function normaliseNotebookJsonForRender(
  notebookJson: Record<string, unknown>
): Record<string, unknown> {
  if (!Array.isArray(notebookJson.cells)) {
    return notebookJson;
  }

  let changed = false;
  const cells = notebookJson.cells.map((cell) => {
    if (!isRecord(cell) || !Array.isArray(cell.outputs)) {
      return cell;
    }

    let cellChanged = false;
    const outputs = cell.outputs.map((output) => {
      if (!isRecord(output)) {
        return output;
      }
      const normalisedOutput = normaliseNotebookOutput(output);
      if (normalisedOutput !== output) {
        cellChanged = true;
      }
      return normalisedOutput;
    });

    if (!cellChanged) {
      return cell;
    }

    changed = true;
    return {
      ...cell,
      outputs,
    };
  });

  if (!changed) {
    return notebookJson;
  }

  return {
    ...notebookJson,
    cells,
  };
}

function normalisePanelOutputs(panel: NotebookPanel): void {
  if (panel.isDisposed || outputNormalisationInFlightPanelIds.has(panel.id)) {
    return;
  }

  const widgets = panel.content.widgets as readonly {
    model?: {
      outputs?: {
        toJSON?: () => Array<Record<string, unknown>>;
        clear?: () => void;
        fromJSON?: (value: Array<Record<string, unknown>>) => void;
      };
    };
  }[];

  outputNormalisationInFlightPanelIds.add(panel.id);
  try {
    for (const widget of widgets) {
      const outputs = widget.model?.outputs;
      if (
        !outputs ||
        typeof outputs.toJSON !== "function" ||
        typeof outputs.clear !== "function" ||
        typeof outputs.fromJSON !== "function"
      ) {
        continue;
      }

      const rawOutputs = outputs.toJSON();
      if (!Array.isArray(rawOutputs) || rawOutputs.length === 0) {
        continue;
      }

      let changed = false;
      const normalisedOutputs = rawOutputs.map((rawOutput) => {
        if (!isRecord(rawOutput)) {
          return rawOutput;
        }
        const nextOutput = normaliseNotebookOutput(rawOutput);
        if (nextOutput !== rawOutput) {
          changed = true;
        }
        return nextOutput;
      });

      if (!changed) {
        continue;
      }

      // Normalise live output models so freshly executed cells do not render list commas.
      outputs.clear();
      outputs.fromJSON(normalisedOutputs);
    }
  } finally {
    outputNormalisationInFlightPanelIds.delete(panel.id);
  }
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
  return `workspace-${pathPrefix}-${fingerprint}/workspace.ipynb`;
}

function splitParentPath(path: string): [string, string] {
  const index = path.lastIndexOf("/");
  if (index < 0) {
    return ["", path];
  }
  return [path.slice(0, index), path.slice(index + 1)];
}

function workspaceRootFromNotebookPath(notebookPath: string): string {
  const [parent] = splitParentPath(notebookPath);
  return parent;
}

function normaliseWorkspaceRelativePath(value: string): string | null {
  const clean = value.replace(/\\/g, "/").trim();
  if (!clean) {
    return null;
  }
  const segments: string[] = [];
  for (const segment of clean.split("/")) {
    const trimmed = segment.trim();
    if (!trimmed || trimmed === ".") {
      continue;
    }
    if (trimmed === "..") {
      return null;
    }
    segments.push(trimmed);
  }
  return segments.length > 0 ? segments.join("/") : null;
}

function aliasWorkspaceRelativePath(relativePath: string): string | null {
  const segments = relativePath.split("/").filter((segment) => Boolean(segment));
  if (segments.length <= 1) {
    return null;
  }
  const alias = segments.slice(1).join("/");
  return alias || null;
}

function dirnameOrEmpty(path: string): string {
  const [parent] = splitParentPath(path);
  return parent;
}

function buildKernelImportPaths(
  notebookPath: string,
  files: WorkspaceFilePayload[]
): string[] {
  const paths = new Set<string>();
  paths.add("/drive");

  const workspaceRoot = workspaceRootFromNotebookPath(notebookPath);
  const workspaceBase = workspaceRoot ? `/drive/${workspaceRoot}` : "/drive";
  paths.add(workspaceBase);

  for (const item of files) {
    const relativePath = normaliseWorkspaceRelativePath(item.relative_path ?? "");
    if (!relativePath) {
      continue;
    }
    const aliasPath = aliasWorkspaceRelativePath(relativePath);
    const candidateDirs = [dirnameOrEmpty(relativePath)];
    if (aliasPath) {
      candidateDirs.push(dirnameOrEmpty(aliasPath));
    }

    for (const candidate of candidateDirs) {
      if (!candidate) {
        continue;
      }
      paths.add(`/drive/${candidate}`);
      if (workspaceRoot) {
        paths.add(`/drive/${workspaceRoot}/${candidate}`);
      }
    }
  }

  return Array.from(paths);
}

function buildKernelRuntimeFiles(
  notebookPath: string,
  files: WorkspaceFilePayload[]
): KernelRuntimeFile[] {
  const workspaceRoot = workspaceRootFromNotebookPath(notebookPath);
  const entries = new Map<string, KernelRuntimeFile>();

  for (const item of files) {
    const relativePath = normaliseWorkspaceRelativePath(item.relative_path ?? "");
    const contentBase64 = item.content_base64;
    if (!relativePath || !contentBase64) {
      continue;
    }
    const aliasPath = aliasWorkspaceRelativePath(relativePath);
    const candidateRelativePaths = [relativePath];
    if (aliasPath) {
      candidateRelativePaths.push(aliasPath);
    }
    if (workspaceRoot) {
      candidateRelativePaths.push(`${workspaceRoot}/${relativePath}`);
      if (aliasPath) {
        candidateRelativePaths.push(`${workspaceRoot}/${aliasPath}`);
      }
    }

    for (const rel of candidateRelativePaths) {
      const cleanRel = rel.replace(/^\/+/, "");
      const targetPath = `/drive/${cleanRel}`;
      entries.set(targetPath, { path: targetPath, contentBase64 });
    }
  }

  return Array.from(entries.values());
}

function encodeUtf8ToBase64(value: string): string {
  return window.btoa(unescape(encodeURIComponent(value)));
}

async function syncKernelRuntime(
  panel: NotebookPanel,
  importPaths: string[],
  runtimeFiles: KernelRuntimeFile[]
): Promise<void> {
  if (importPaths.length === 0 && runtimeFiles.length === 0) {
    return;
  }
  try {
    await panel.sessionContext.ready;
  } catch {
    return;
  }
  const kernel = panel.sessionContext.session?.kernel;
  if (!kernel) {
    return;
  }

  for (const item of runtimeFiles) {
    const encodedFilePayload = encodeUtf8ToBase64(
      JSON.stringify({
        path: item.path,
        content_base64: item.contentBase64,
      })
    );
    const fileCode = [
      "import os, json, base64",
      `_item = json.loads(base64.b64decode("${encodedFilePayload}").decode("utf-8"))`,
      "_path = _item.get('path', '')",
      "_data = _item.get('content_base64', '')",
      "if isinstance(_path, str) and _path and isinstance(_data, str) and _data:",
      "    _dir = os.path.dirname(_path)",
      "    if _dir:",
      "        os.makedirs(_dir, exist_ok=True)",
      "    with open(_path, 'wb') as _f:",
      "        _f.write(base64.b64decode(_data))",
    ].join("\n");
    try {
      const future = kernel.requestExecute({
        code: fileCode,
        silent: true,
        store_history: false,
        stop_on_error: false,
      });
      await future.done;
    } catch {
      // Best effort only.
    }
  }

  const importPayload = JSON.stringify(importPaths);
  const encodedImportPayload = encodeUtf8ToBase64(importPayload);
  const importCode = [
    "import os, sys, json, base64, importlib",
    `_paths = json.loads(base64.b64decode("${encodedImportPayload}").decode("utf-8"))`,
    "_cwd_candidates = []",
    "for _path in _paths:",
    "    if not isinstance(_path, str) or not _path:",
    "        continue",
    "    if _path.startswith('/drive/') and not os.path.isdir(_path):",
    "        try:",
    "            os.makedirs(_path, exist_ok=True)",
    "        except OSError:",
    "            pass",
    "    if os.path.isdir(_path):",
    "        if _path not in sys.path:",
    "            sys.path.insert(0, _path)",
    "        _cwd_candidates.append(_path)",
    "if _cwd_candidates:",
    "    _preferred = _cwd_candidates[1] if len(_cwd_candidates) > 1 else _cwd_candidates[0]",
    "    if isinstance(_preferred, str) and _preferred and os.path.isdir(_preferred):",
    "        os.chdir(_preferred)",
    "importlib.invalidate_caches()",
  ].join("\n");

  try {
    const future = kernel.requestExecute({
      code: importCode,
      silent: true,
      store_history: false,
      stop_on_error: false,
    });
    await future.done;
  } catch {
    // Best effort only.
  }
}

async function ensureDirectoryPath(
  app: JupyterFrontEnd,
  directoryPath: string
): Promise<void> {
  if (!directoryPath) {
    return;
  }
  const segments = directoryPath.split("/").filter((segment) => Boolean(segment));
  let currentPath = "";
  for (const segment of segments) {
    currentPath = currentPath ? `${currentPath}/${segment}` : segment;
    try {
      await app.serviceManager.contents.get(currentPath, { content: false });
    } catch {
      await app.serviceManager.contents.save(currentPath, {
        type: "directory",
      });
    }
  }
}

async function deletePathIfExists(
  app: JupyterFrontEnd,
  targetPath: string
): Promise<void> {
  try {
    await app.serviceManager.contents.delete(targetPath);
  } catch {
    // Best effort cleanup.
  }
}

async function clearInjectedRuntimePaths(app: JupyterFrontEnd): Promise<void> {
  if (injectedRuntimePaths.size === 0) {
    return;
  }

  // Delete deeper paths first to minimise directory-not-empty errors.
  const ordered = Array.from(injectedRuntimePaths).sort(
    (a, b) => b.length - a.length
  );
  for (const targetPath of ordered) {
    await deletePathIfExists(app, targetPath);
    const [parent] = splitParentPath(targetPath);
    if (parent) {
      await deletePathIfExists(app, parent);
    }
  }
  injectedRuntimePaths.clear();
}

async function saveWorkspaceFiles(
  app: JupyterFrontEnd,
  notebookPath: string,
  files: WorkspaceFilePayload[]
): Promise<Set<string>> {
  const writtenPaths = new Set<string>();
  if (!files.length) {
    return writtenPaths;
  }

  const workspaceRoot = workspaceRootFromNotebookPath(notebookPath);
  for (const item of files) {
    const relativePath = normaliseWorkspaceRelativePath(item.relative_path ?? "");
    const contentBase64 = item.content_base64;
    if (!relativePath || !contentBase64) {
      continue;
    }

    const primaryPath = workspaceRoot
      ? `${workspaceRoot}/${relativePath}`
      : relativePath;
    const aliasRelativePath = aliasWorkspaceRelativePath(relativePath);
    const candidatePaths = [primaryPath];
    if (aliasRelativePath) {
      candidatePaths.push(
        workspaceRoot ? `${workspaceRoot}/${aliasRelativePath}` : aliasRelativePath
      );
    }
    candidatePaths.push(relativePath);
    if (aliasRelativePath) {
      candidatePaths.push(aliasRelativePath);
    }

    const dedupedPaths = Array.from(new Set(candidatePaths));
    for (const targetPath of dedupedPaths) {
      const [parent] = splitParentPath(targetPath);
      await ensureDirectoryPath(app, parent);
      await withTimeout(
        app.serviceManager.contents.save(targetPath, {
          type: "file",
          format: "base64",
          content: contentBase64,
        }),
        SAVE_TIMEOUT_MS,
        "Workspace file save"
      );
      writtenPaths.add(targetPath);
    }
  }
  return writtenPaths;
}

function ensureWorkspaceNotebookScopeClass(): void {
  document.body.classList.add(WORKSPACE_NOTEBOOK_SCOPE_CLASS);
}

function buildWorkspaceBaseLayoutCss(scope: string): string {
  return `
    ${scope} {
      --gc-workspace-bg: #ffffff;
      --jp-notebook-max-width: 100%;
      --jp-notebook-padding-offset: 0px;
      --jp-private-sidebar-tab-width: 0px;
      --gc-notebook-readable-min-width: 580px;
      --gc-notebook-right-gutter: clamp(
        0px,
        calc(var(--jp-cell-prompt-width, 64px) + 8px),
        96px
      );
      height: 100% !important;
      background: var(--gc-workspace-bg) !important;
    }

    /* Shell layout override: allow Lumino to work normally but use flex for the shell.
       We remove absolute positioning overrides to stop fighting Lumino and let it calculate. */
    ${scope} .jp-LabShell {
      display: flex !important;
      flex-direction: column !important;
      width: 100% !important;
      height: 100% !important;
    }

    /* Menu bar: visible, natural height */
    ${scope} #jp-top-panel {
      order: 1 !important;
      display: flex !important;
      visibility: visible !important;
      flex-shrink: 0 !important;
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      height: auto !important;
      background: var(--gc-workspace-bg) !important;
    }
    
    ${scope} #jp-menu-panel {
      order: 2 !important;
      display: flex !important;
      visibility: visible !important;
      flex-shrink: 0 !important;
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      height: auto !important;
      background: var(--gc-workspace-bg) !important;
    }

    /* Main content: fills remaining vertical space. */
    ${scope} #jp-main-content-panel {
      order: 3 !important;
      display: flex !important;
      flex-direction: column !important;
      flex: 1 1 0 !important;
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      height: 100% !important;
      min-width: 0 !important;
      min-height: 0 !important;
      overflow: hidden !important;
      background: var(--gc-workspace-bg) !important;
    }

    /* Panels below main-content fill their parent */
    ${scope} .jp-NotebookPanel {
      display: flex !important;
      flex-direction: column !important;
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      height: 100% !important;
      min-width: 0 !important;
      min-height: 0 !important;
      background: var(--gc-workspace-bg) !important;
    }
    
    ${scope} .jp-StatusBar,
    ${scope} .jp-StatusBar-Widget,
    ${scope} [class*="jp-StatusBar-"] {
      display: none !important;
    }
    ${scope} .jp-SideBar,
    ${scope} .jp-LeftStackedPanel,
    ${scope} .jp-RightStackedPanel,
    ${scope} #jp-left-stack,
    ${scope} #jp-right-stack {
      width: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      flex: 0 0 0 !important;
      border: none !important;
      margin: 0 !important;
      padding: 0 !important;
      overflow: hidden !important;
      visibility: hidden !important;
    }
    ${scope} #jp-main-content-panel > .jp-SideBar.jp-mod-left,
    ${scope} #jp-main-content-panel > .jp-SideBar.jp-mod-right {
      display: none !important;
      width: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      visibility: hidden !important;
    }

    /* Lumino split panels: fill parent entirely via Flexbox, ignoring absolute sizing. */
    ${scope} #jp-main-vsplit-panel,
    ${scope} #jp-main-split-panel,
    ${scope} #jp-main-dock-panel {
      display: flex !important;
      flex-direction: column !important;
      flex: 1 1 0 !important;
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      height: 100% !important;
      min-height: 0 !important;
      min-width: 0 !important;
      max-width: none !important;
      background: var(--gc-workspace-bg) !important;
    }
    ${scope} .lm-SplitPanel-handle {
      display: none !important;
      width: 0 !important;
      height: 0 !important;
      min-width: 0 !important;
      max-width: 0 !important;
      border: none !important;
      pointer-events: none !important;
    }
    ${scope} #jp-main-dock-panel {
      padding: 0 !important;
    }
    
    /* DockPanel internals override to flex */
    ${scope} .lm-DockPanel-tabBar {
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      flex: 0 0 auto !important;
      height: auto !important;
      min-height: 0 !important;
      min-width: 0 !important;
    }
    ${scope} .lm-DockPanel-widget {
      position: relative !important;
      top: auto !important;
      left: auto !important;
      width: 100% !important;
      flex: 1 1 0 !important;
      height: auto !important;
      min-height: 0 !important;
      min-width: 0 !important;
    }

    /* Notebook canvas edge-to-edge. */
    ${scope} .jp-NotebookPanel .jp-NotebookPanel-toolbar {
      flex: 0 0 auto !important;
      width: 100% !important;
      min-width: 0 !important;
      padding-left: 0 !important;
      padding-right: var(--gc-notebook-right-gutter) !important;
      background: var(--gc-workspace-bg) !important;
      overflow: visible !important;
      flex-wrap: wrap !important;
    }
    ${scope} .jp-NotebookPanel .jp-WindowedPanel-outer {
      flex: 1 1 0 !important;
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
      height: 100% !important;
      min-height: 0 !important;
      padding-left: 0 !important;
      padding-right: 0 !important;
      overflow: auto !important; /* Allow generic scrolling */
      background: var(--gc-workspace-bg) !important;
    }
    ${scope} .jp-NotebookPanel .jp-WindowedPanel-inner,
    ${scope} .jp-NotebookPanel .jp-WindowedPanel-outer > *,
    ${scope} .jp-NotebookPanel .jp-Notebook {
      width: 100% !important;
      min-width: var(--gc-notebook-readable-min-width) !important; /* Maintain minimum readable width, triggering horizontal scroll when smaller */
      max-width: none !important;
      box-sizing: border-box !important;
      padding-left: 0 !important;
      margin: 0 !important;
      background: var(--gc-workspace-bg) !important;
    }
    ${scope} .jp-NotebookPanel .jp-Cell,
    ${scope} .jp-NotebookPanel .jp-Cell-inputWrapper,
    ${scope} .jp-NotebookPanel .jp-OutputArea,
    ${scope} .jp-NotebookPanel .jp-OutputArea-child {
      width: 100% !important;
      min-width: 0 !important;
      max-width: none !important;
    }
    ${scope} .jp-NotebookPanel .jp-OutputArea-output {
      max-width: 100% !important;
    }
    /* Plain-text outputs keep whitespace so ASCII tables stay aligned. */
    ${scope} .jp-NotebookPanel .jp-OutputArea-output pre,
    ${scope} .jp-NotebookPanel .jp-ThemedContainer .jp-RenderedText pre {
      white-space: pre !important;
      word-break: normal !important;
      overflow-wrap: normal !important;
      overflow-x: auto !important;
    }
  `;
}

function buildWorkspaceNotebookCss(): string {
  const scope = `body.${WORKSPACE_NOTEBOOK_SCOPE_CLASS}`;
  return buildWorkspaceBaseLayoutCss(scope);
}

let injectedWorkspaceCssSignature = "";

function injectWorkspaceChromeStyles(): void {
  ensureWorkspaceNotebookScopeClass();
  const css = buildWorkspaceNotebookCss();
  // Skip re-injection if content is unchanged. Re-setting textContent causes
  // the browser to re-parse the entire stylesheet, briefly removing CSS
  // overrides and exposing Lumino's inline styles for one frame.
  if (css === injectedWorkspaceCssSignature) {
    return;
  }
  let style = document.getElementById(WORKSPACE_STYLE_ID) as HTMLStyleElement | null;
  if (!style) {
    style = document.createElement("style");
    style.id = WORKSPACE_STYLE_ID;
    document.head.appendChild(style);
  }
  style.textContent = css;
  injectedWorkspaceCssSignature = css;
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
  injectWorkspaceChromeStyles();

  // Keep the notebook in full-width mode for consistent edge alignment.
  panel.addClass("jp-mod-fullwidth");
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

function refreshLayoutTarget(
  candidate: unknown,
  options: { forceMeasure?: boolean } = {}
): void {
  if (!candidate || typeof candidate !== "object") {
    return;
  }
  const target = candidate as LayoutRefreshTarget;
  target.fit?.();
  target.update?.();
  if (options.forceMeasure && target.node instanceof HTMLElement) {
    // Force one synchronous measurement so browser layout catches split width changes.
    void target.node.getBoundingClientRect();
  }
}

const NOTEBOOK_READABLE_MIN_WIDTH_PX = 680;
const NOTEBOOK_ANOMALY_RECOVERY_COOLDOWN_MS = 150;
const NOTEBOOK_FORCED_SETTLE_COOLDOWN_MS = 200;

function toFinitePositiveNumber(value: unknown): number {
  if (typeof value !== "number") {
    return 0;
  }
  if (!Number.isFinite(value)) {
    return 0;
  }
  return value > 0 ? value : 0;
}

function alignWorkspaceBackground(panel: NotebookPanel | null): void {
  const workspaceBackground = "var(--gc-workspace-bg, #ffffff)";
  const fillNodes: Array<Element | null> = [
    document.getElementById("jp-main-content-panel"),
    document.getElementById("jp-main-vsplit-panel"),
    document.getElementById("jp-main-split-panel"),
    document.getElementById("jp-main-dock-panel"),
    panel?.node ?? null,
    (panel?.content as { node?: Element | null } | undefined)?.node ?? null,
  ];

  for (const node of fillNodes) {
    if (!(node instanceof HTMLElement)) {
      continue;
    }
    if (node.style.background !== workspaceBackground) {
      node.style.background = workspaceBackground;
    }
  }
}

// Obsolete: layout anomalies, manual measurement and JS anomaly recovery loops are removed.
// We let Lumino and native CSS Handle Flex and Resize natively.

function parseLayoutRefreshReason(
  reason: unknown,
  phase: LayoutRefreshPhase
): LayoutRefreshReason {
  if (
    reason === "split-drag" ||
    reason === "split-settle" ||
    reason === "window-resize" ||
    reason === "observer-settle"
  ) {
    return reason;
  }
  return phase === "drag" ? "split-drag" : "split-settle";
}

function parseLayoutRefreshRequest(message: BridgeMessage): LayoutRefreshRequest {
  const phase: LayoutRefreshPhase =
    message.phase === "settle" || message.final_pass === true ? "settle" : "drag";
  return {
    phase,
    reason: parseLayoutRefreshReason(message.reason, phase),
    paneWidth: Math.round(toFinitePositiveNumber(message.pane_width)),
    paneHeight: Math.round(toFinitePositiveNumber(message.pane_height)),
    requestTs: Math.round(toFinitePositiveNumber(message.request_ts)) || Date.now(),
  };
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
  const activeWorkspaceRoot = workspaceRootFromNotebookPath(notebookPath);
  try {
    const root = await app.serviceManager.contents.get("", { content: true });
    const items = Array.isArray(root.content)
      ? root.content
      : [];
    for (const item of items) {
      if (item.type === "directory") {
        if (!item.path || !item.path.startsWith("workspace-")) {
          continue;
        }
        if (item.path === activeWorkspaceRoot) {
          continue;
        }
        try {
          await app.serviceManager.contents.delete(item.path);
        } catch {
          // Best effort cleanup.
        }
        continue;
      }
      if (item.type === "notebook") {
        if (!item.path || item.path === notebookPath) {
          continue;
        }
        try {
          await app.serviceManager.contents.delete(item.path);
        } catch {
          // Best effort cleanup.
        }
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
    markBridgeRuntime({
      pluginId: "guided-cursor-jupyterlite-bridge",
      activatedAt: Date.now(),
      ready: false,
      startupWarnings: [],
    });

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
          const rawNotebookJson = isRecord(message.notebook_json)
            ? message.notebook_json
            : EMPTY_NOTEBOOK;
          // Standardise Jupyter text-array fields before rendering to avoid comma artefacts.
          const notebookJson = withAvailableKernelMetadata(
            app,
            normaliseNotebookJsonForRender(rawNotebookJson)
          );
          const workspaceFiles = Array.isArray(message.workspace_files)
            ? message.workspace_files
            : [];
          const notebookPath = toNotebookPath(message.notebook_key);
          const notebookTitle = normaliseNotebookTitle(
            message.notebook_title ?? message.notebook_name
          );
          const [notebookDirectory] = splitParentPath(notebookPath);
          runtimeSyncToken += 1;
          pendingKernelImportPaths = buildKernelImportPaths(
            notebookPath,
            workspaceFiles
          );
          pendingKernelRuntimeFiles = buildKernelRuntimeFiles(
            notebookPath,
            workspaceFiles
          );
          activeNotebookPath = notebookPath;
          activeNotebookTitle = notebookTitle;

          await clearInjectedRuntimePaths(app);
          await ensureDirectoryPath(app, notebookDirectory);
          const writtenPaths = await saveWorkspaceFiles(app, notebookPath, workspaceFiles);
          for (const path of writtenPaths) {
            injectedRuntimePaths.add(path);
          }

          if (activePanel?.context.path === notebookPath) {
            const model = activePanel.context.model as {
              fromJSON?: (value: Record<string, unknown>) => void;
            };
            if (model.fromJSON) {
              model.fromJSON(notebookJson);
              normalisePanelOutputs(activePanel);
              void activePanel.context.save();
              applyNotebookPresentation(activePanel, notebookTitle, app);
              syncedPanelTokenById.set(activePanel.id, runtimeSyncToken);
              await syncKernelRuntime(
                activePanel,
                pendingKernelImportPaths,
                pendingKernelRuntimeFiles
              );
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
          reply(message, {
            notebook_json: normaliseNotebookJsonForRender(notebookJson),
          });
          return;
        }

        if (message.command === "refresh-layout") {
          // No-Op. Layout is now entirely handled naturally by CSS flexbox and native window resize.
          reply(message, { ok: true });
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

    const startupWarnings: string[] = [];
    const runStartupStep = (label: string, fn: () => void) => {
      try {
        fn();
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        startupWarnings.push(`${label}: ${message}`);
        console.error(`[jupyterlite-bridge] ${label} failed`, error);
      }
    };

    runStartupStep("enforceWorkspaceShellMode", () => {
      enforceWorkspaceShellMode(app);
    });
    runStartupStep("injectWorkspaceChromeStyles", () => {
      injectWorkspaceChromeStyles();
    });
    runStartupStep("installDownloadCommandOverride", () => {
      installDownloadCommandOverride(app);
    });
    // Obsolete steps eliminated

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

    if (startupWarnings.length > 0) {
      markBridgeRuntime({ startupWarnings });
    }

    // Emit ready more than once to avoid a one-off timing race on fast loads.
    announceReady();
    window.setTimeout(announceReady, 250);
    window.setTimeout(announceReady, 1000);
  },
};

export default plugin;
