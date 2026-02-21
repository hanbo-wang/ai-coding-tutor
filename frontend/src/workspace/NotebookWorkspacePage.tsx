import { useCallback, useRef } from "react";
import { useParams } from "react-router-dom";
import Split from "react-split";

import { useAuth } from "../auth/useAuth";
import { NotebookPanel, NotebookPanelHandle } from "./NotebookPanel";
import { WorkspaceChatPanel } from "./WorkspaceChatPanel";

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

  if (!notebookId) {
    return (
      <div className="h-full flex items-center justify-center text-gray-600">
        Notebook ID is missing.
      </div>
    );
  }

  const workspaceKey = `${user?.id ?? "anonymous"}:personal:${notebookId}`;

  return (
    <div className="h-full bg-gray-100">
      <Split
        sizes={[60, 40]}
        minSize={300}
        gutterSize={10}
        className="split-root h-full flex"
      >
        <div className="min-w-0 h-full">
          <NotebookPanel
            key={workspaceKey}
            ref={panelRef}
            notebookId={notebookId}
            mode="personal"
            workspaceKey={workspaceKey}
          />
        </div>
        <div className="min-w-0 h-full">
          <WorkspaceChatPanel
            sessionType="notebook"
            moduleId={notebookId}
            getCellContext={getCellContext}
          />
        </div>
      </Split>
    </div>
  );
}
