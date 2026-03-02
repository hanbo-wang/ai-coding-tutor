import { useCallback, useEffect } from "react";





interface UseWorkspaceSplitRefreshResult {
  onDrag: () => void;
  onDragEnd: () => void;
  cleanup: () => void;
}

/**
 * Shared split-gutter refresh scheduler for notebook workspace pages.
 * Layout refreshes are no longer needed, as CSS Flexbox and native browser resizing handles this automatically.
 */
export function useWorkspaceSplitRefresh(): UseWorkspaceSplitRefreshResult {
  const cleanup = useCallback(() => { }, []);
  const onDrag = useCallback(() => { }, []);
  const onDragEnd = useCallback(() => { }, []);

  useEffect(() => cleanup, [cleanup]);

  return { onDrag, onDragEnd, cleanup };
}
