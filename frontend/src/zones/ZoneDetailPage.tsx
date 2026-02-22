import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { apiFetch } from "../api/http";
import { ZoneDetail } from "../api/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function ZoneDetailPage() {
  const { zoneId } = useParams<{ zoneId: string }>();
  const navigate = useNavigate();
  const [zone, setZone] = useState<ZoneDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!zoneId) {
      setError("Zone ID is missing.");
      setIsLoading(false);
      return;
    }

    const loadZone = async () => {
      try {
        const detail = await apiFetch<ZoneDetail>(`/api/zones/${zoneId}`);
        setZone(detail);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load zone.");
      } finally {
        setIsLoading(false);
      }
    };
    void loadZone();
  }, [zoneId]);

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-600">
        Loading zone...
      </div>
    );
  }

  if (!zone) {
    return (
      <div className="h-full flex items-center justify-center text-red-600">
        {error || "Zone not found."}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <button
          type="button"
          onClick={() => navigate("/learning-hub")}
          className="mb-4 text-sm text-gray-600 hover:text-brand"
        >
          ← Back to Learning Hub
        </button>

        <h1 className="text-2xl font-bold text-brand">{zone.title}</h1>
        <p className="mt-1 text-sm text-gray-600">
          {zone.description || "No description yet."}
        </p>

        {zone.notebooks.length === 0 ? (
          <div className="mt-6 rounded-lg bg-white p-8 text-center text-gray-500">
            No notebooks in this zone yet.
          </div>
        ) : (
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {zone.notebooks.map((notebook) => (
              <button
                key={notebook.id}
                type="button"
                onClick={() =>
                  navigate(`/zone-notebook/${zone.id}/${notebook.id}`)
                }
                className="rounded-lg border border-gray-200 bg-white p-5 text-left shadow-sm hover:border-accent hover:shadow"
              >
                <div className="mb-2 flex items-start justify-between gap-3">
                  <h2 className="text-base font-semibold text-brand">{notebook.title}</h2>
                  {notebook.has_progress && (
                    <span className="rounded-full bg-accent-light px-2 py-0.5 text-[11px] font-medium text-brand">
                      In Progress
                    </span>
                  )}
                </div>
                {notebook.description && (
                  <p className="text-sm text-gray-600">{notebook.description}</p>
                )}
                <p className="mt-3 text-xs text-gray-500">
                  {formatSize(notebook.size_bytes)}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
