import { useCallback, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Split from "react-split";

import { apiFetch } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { NotebookPanel, NotebookPanelHandle } from "./NotebookPanel";
import { WorkspaceChatPanel } from "./WorkspaceChatPanel";
import { useWorkspaceSplitRefresh } from "./useWorkspaceSplitRefresh";

export function ZoneNotebookWorkspacePage() {
  const { user } = useAuth();
  const { zoneId, notebookId } = useParams<{
    zoneId: string;
    notebookId: string;
  }>();

  const panelRef = useRef<NotebookPanelHandle | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [error, setError] = useState("");

  const getCellContext = useCallback(async () => {
    if (!panelRef.current) {
      return { cellCode: "", errorOutput: null };
    }
    return panelRef.current.getCellContext();
  }, []);

  const { onDrag, onDragEnd } = useWorkspaceSplitRefresh();

  const handleReset = async () => {
    if (!zoneId || !notebookId) return;
    const confirmed = window.confirm(
      "Reset to original notebook content? Your saved progress will be removed."
    );
    if (!confirmed) return;

    try {
      await apiFetch(`/api/zones/${zoneId}/notebooks/${notebookId}/progress`, {
        method: "DELETE",
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reset notebook.";
      // A 404 simply means no edits were ever made, which is an acceptable success state.
      if (!message.toLowerCase().includes("progress not found")) {
        setError(message);
        return;
      }
    }

    // Always reset the workspace state when a reset successfully occurred (or there was no progress to begin with).
    setReloadKey((value) => value + 1);
    setError("");
  };

  if (!zoneId || !notebookId) {
    return (
      <div className="h-full flex items-center justify-center text-gray-600">
        Notebook route is invalid.
      </div>
    );
  }

  const workspaceKey = `${user?.id ?? "anonymous"}:zone:${zoneId}:${notebookId}`;

  return (
    <div className="h-full min-h-0 overflow-hidden bg-gray-100 flex flex-col">
      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="relative min-h-0 min-w-0 flex-1 overflow-hidden">
        <Split
          sizes={[60, 40]}
          minSize={[650, 360]}
          gutterSize={10}
          dragInterval={12}
          onDrag={onDrag}
          onDragEnd={onDragEnd}
          className="split-root h-full min-h-0 overflow-hidden flex"
        >
          <div className="min-w-0 min-h-0 h-full overflow-hidden flex flex-col relative">
            <div className="absolute top-[2px] right-2 z-10 flex items-center justify-end">
              <button
                type="button"
                onClick={() => void handleReset()}
                className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-xs text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1"
              >
                Reset to Original
              </button>
            </div>
            <div className="relative min-h-0 flex-1 overflow-hidden">
              <NotebookPanel
                key={`${workspaceKey}-${reloadKey}`}
                ref={panelRef}
                notebookId={notebookId}
                mode="zone"
                zoneId={zoneId}
                reloadKey={reloadKey}
                workspaceKey={workspaceKey}
              />
            </div>
          </div>
          <div className="min-w-0 min-h-0 h-full overflow-hidden">
            <WorkspaceChatPanel
              key={`workspace-chat:zone:${zoneId}:${notebookId}`}
              sessionType="zone"
              moduleId={notebookId}
              getCellContext={getCellContext}
            />
          </div>
        </Split>
      </div>
    </div>
  );
}
