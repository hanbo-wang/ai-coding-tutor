import { useCallback, useRef } from "react";
import { useParams } from "react-router-dom";
import Split from "react-split";

import { useAuth } from "../auth/useAuth";
import { NotebookPanel, NotebookPanelHandle } from "./NotebookPanel";
import { WorkspaceChatPanel } from "./WorkspaceChatPanel";
import { useWorkspaceSplitRefresh } from "./useWorkspaceSplitRefresh";

export function NotebookWorkspacePage() {
  const { user } = useAuth();
  const { notebookId } = useParams<{ notebookId: string }>();
  const panelRef = useRef<NotebookPanelHandle | null>(null);

  const getCellContext = useCallback(async () => {
    if (!panelRef.current) {
      return { cellCode: "", errorOutput: null };
    }
    return panelRef.current.getCellContext();
  }, []);

  const { onDrag, onDragEnd } = useWorkspaceSplitRefresh();

  if (!notebookId) {
    return (
      <div className="h-full flex items-center justify-center text-gray-600">
        Notebook ID is missing.
      </div>
    );
  }

  const workspaceKey = `${user?.id ?? "anonymous"}:personal:${notebookId}`;

  return (
    <div className="h-full min-h-0 overflow-hidden bg-gray-100">
      <Split
        sizes={[60, 40]}
        minSize={[650, 360]}
        gutterSize={10}
        dragInterval={12}
        onDrag={onDrag}
        onDragEnd={onDragEnd}
        className="split-root h-full min-h-0 overflow-hidden flex"
      >
        <div className="min-w-0 min-h-0 h-full overflow-hidden">
          <NotebookPanel
            key={workspaceKey}
            ref={panelRef}
            notebookId={notebookId}
            mode="personal"
            workspaceKey={workspaceKey}
          />
        </div>
        <div className="min-w-0 min-h-0 h-full overflow-hidden">
          <WorkspaceChatPanel
            key={`workspace-chat:notebook:${notebookId}`}
            sessionType="notebook"
            moduleId={notebookId}
            getCellContext={getCellContext}
          />
        </div>
      </Split>
    </div>
  );
}
