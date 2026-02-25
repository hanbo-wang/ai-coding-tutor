import { useEffect, useState } from "react";

import { apiFetch } from "../api/http";
import { HealthModelsResponse, HealthModelProviderStatus } from "../api/types";

type LoadState = "idle" | "loading" | "refreshing";

function formatCheckedAt(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function ProviderHealthTable({
  title,
  groups,
}: {
  title: string;
  groups: Record<string, HealthModelProviderStatus>;
}) {
  const providers = Object.entries(groups);
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-brand">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
            <tr>
              <th className="px-4 py-2">Provider</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Checked Models</th>
              <th className="px-4 py-2">Available Models</th>
            </tr>
          </thead>
          <tbody>
            {providers.map(([provider, status]) => {
              const providerLabel =
                provider === "google" && status.transport
                  ? `google (${status.transport})`
                  : provider;
              const checkedEntries = Object.entries(status.checked_models || {});
              return (
                <tr key={providerLabel} className="border-b border-gray-50 align-top">
                  <td className="px-4 py-3 font-medium text-gray-800">{providerLabel}</td>
                  <td className="px-4 py-3">
                    <div
                      className={`inline-flex rounded px-2 py-1 text-xs font-medium ${
                        status.configured
                          ? "bg-green-50 text-green-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {status.configured ? "Configured" : "Not configured"}
                    </div>
                    {status.reason && (
                      <p className="mt-2 max-w-sm text-xs leading-5 text-gray-500">
                        {status.reason}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {checkedEntries.length === 0 ? (
                      <span className="text-xs text-gray-500">No smoke checks run</span>
                    ) : (
                      <ul className="space-y-1">
                        {checkedEntries.map(([modelId, ok]) => (
                          <li key={modelId} className="text-xs text-gray-700">
                            <code className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px]">
                              {modelId}
                            </code>{" "}
                            <span className={ok ? "text-green-700" : "text-red-700"}>
                              {ok ? "OK" : "FAILED"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {status.available_models.length === 0 ? (
                      <span className="text-xs text-gray-500">None</span>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {status.available_models.map((modelId) => (
                          <code
                            key={modelId}
                            className="rounded bg-green-50 px-2 py-1 text-[11px] text-green-800"
                          >
                            {modelId}
                          </code>
                        ))}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ConfiguredModelTable({
  title,
  rows,
}: {
  title: string;
  rows: Record<string, string>;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="border-b border-gray-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-brand">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
            <tr>
              <th className="px-4 py-2">Provider</th>
              <th className="px-4 py-2">Configured Model</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(rows).map(([provider, modelId]) => (
              <tr key={provider} className="border-b border-gray-50">
                <td className="px-4 py-3 font-medium text-gray-800">{provider}</td>
                <td className="px-4 py-3">
                  <code className="rounded bg-gray-100 px-2 py-1 text-[11px]">
                    {modelId}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function HealthPage() {
  const [data, setData] = useState<HealthModelsResponse | null>(null);
  const [error, setError] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("idle");

  const loadHealth = async (force = false) => {
    setLoadState((prev) => (prev === "idle" ? "loading" : "refreshing"));
    try {
      const query = force ? "?force=true" : "";
      const result = await apiFetch<HealthModelsResponse>(`/api/health/ai/models${query}`);
      setData(result);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load health data.");
    } finally {
      setLoadState("idle");
    }
  };

  useEffect(() => {
    void loadHealth(false);
  }, []);

  const isLoading = loadState === "loading";
  const isRefreshing = loadState === "refreshing";

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold text-brand">System Health</h1>
            <p className="mt-1 text-sm text-gray-600">
              Current configured models and smoke-tested available models.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadHealth(true)}
            disabled={isLoading || isRefreshing}
            className="inline-flex h-9 items-center justify-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isRefreshing ? "Refreshing..." : "Run Smoke Checks Again"}
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {isLoading && !data ? (
          <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
            Loading health data...
          </div>
        ) : data ? (
          <div className="space-y-6">
            <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex flex-wrap gap-3 text-sm">
                <div className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-gray-700">
                  Checked:{" "}
                  <span className="font-medium">{formatCheckedAt(data.checked_at)}</span>
                </div>
                <div className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-gray-700">
                  Cached:{" "}
                  <span className="font-medium">{data.cached ? "Yes" : "No"}</span>
                </div>
              </div>
              <div className="mt-4 rounded-md border border-blue-100 bg-blue-50/60 px-4 py-3">
                <p className="text-sm text-gray-700">
                  <span className="font-semibold text-brand">Current LLM:</span>{" "}
                  <code className="rounded bg-white px-2 py-0.5 text-[11px]">
                    {data.current.active_llm.provider}
                  </code>{" "}
                  <code className="rounded bg-white px-2 py-0.5 text-[11px]">
                    {data.current.active_llm.model}
                  </code>
                  {data.current.active_llm.provider === "google" &&
                    data.current.google_gemini_transport && (
                      <>
                        {" "}
                        <span className="text-gray-500">(transport:</span>{" "}
                        <code className="rounded bg-white px-2 py-0.5 text-[11px]">
                          {data.current.google_gemini_transport}
                        </code>
                        <span className="text-gray-500">)</span>
                      </>
                    )}
                </p>
                <p className="mt-2 text-sm text-gray-700">
                  <span className="font-semibold text-brand">Current embeddings:</span>{" "}
                  <code className="rounded bg-white px-2 py-0.5 text-[11px]">
                    {data.current.active_embedding.provider}
                  </code>{" "}
                  <code className="rounded bg-white px-2 py-0.5 text-[11px]">
                    {data.current.active_embedding.model}
                  </code>
                </p>
              </div>
            </section>

            <div className="grid gap-6 lg:grid-cols-2">
              <ConfiguredModelTable
                title="Configured LLM Models"
                rows={data.current.llm_models}
              />
              <ConfiguredModelTable
                title="Configured Embedding Models"
                rows={data.current.embedding_models}
              />
            </div>

            <ProviderHealthTable
              title="Smoke-Tested Available LLM Models"
              groups={data.smoke_tested_models.llm}
            />
            <ProviderHealthTable
              title="Smoke-Tested Available Embedding Models"
              groups={data.smoke_tested_models.embeddings}
            />
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 bg-white p-8 text-center text-sm text-gray-500 shadow-sm">
            No health data available yet.
          </div>
        )}
      </div>
    </div>
  );
}
