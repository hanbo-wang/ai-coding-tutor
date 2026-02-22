import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api/http";
import { LearningZone } from "../api/types";

export function LearningHubPage() {
  const navigate = useNavigate();
  const [zones, setZones] = useState<LearningZone[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const loadZones = async () => {
      try {
        const data = await apiFetch<LearningZone[]>("/api/zones");
        setZones(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load zones.");
      } finally {
        setIsLoading(false);
      }
    };
    void loadZones();
  }, []);

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <h1 className="text-2xl font-bold text-brand">Learning Hub</h1>
        <p className="mt-1 text-sm text-gray-600">
          Browse curated learning zones and open guided notebooks.
        </p>

        {error && (
          <div className="mt-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {isLoading ? (
          <div className="mt-6 rounded-lg bg-white p-8 text-center text-gray-500">
            Loading zones...
          </div>
        ) : zones.length === 0 ? (
          <div className="mt-6 rounded-lg bg-white p-8 text-center text-gray-500">
            No zones available yet.
          </div>
        ) : (
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {zones.map((zone) => (
              <button
                key={zone.id}
                type="button"
                onClick={() => navigate(`/zones/${zone.id}`)}
                className="rounded-lg border border-gray-200 bg-white p-5 text-left shadow-sm hover:border-accent hover:shadow"
              >
                <h2 className="text-lg font-semibold text-brand">{zone.title}</h2>
                <p className="mt-1 line-clamp-3 text-sm text-gray-600">
                  {zone.description || "No description yet."}
                </p>
                <p className="mt-3 text-xs text-gray-500">
                  {zone.notebook_count} notebook
                  {zone.notebook_count === 1 ? "" : "s"}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
