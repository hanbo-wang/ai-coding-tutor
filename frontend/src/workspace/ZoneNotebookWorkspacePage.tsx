import { useCallback, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Split from "react-split";

import { apiFetch } from "../api/http";
import { useAuth } from "../auth/useAuth";
import { NotebookPanel, NotebookPanelHandle } from "./NotebookPanel";
import { WorkspaceChatPanel } from "./WorkspaceChatPanel";

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
      setReloadKey((value) => value + 1);
      setError("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reset notebook.";
      if (message.toLowerCase().includes("progress not found")) {
        setReloadKey((value) => value + 1);
        setError("");
        return;
      }
      setError(message);
    }
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
    <div className="h-full bg-gray-100 flex flex-col">
      {error && (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <Split
          sizes={[60, 40]}
          minSize={300}
          gutterSize={10}
          className="split-root h-full flex"
        >
          <div className="relative min-w-0 h-full">
            <button
              type="button"
              onClick={() => void handleReset()}
              className="absolute right-3 top-3 z-20 rounded-md border border-gray-300 bg-white/95 px-2.5 py-1 text-xs text-gray-700 shadow-sm hover:bg-white"
            >
              Reset to Original
            </button>
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
          <div className="min-w-0 h-full">
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
