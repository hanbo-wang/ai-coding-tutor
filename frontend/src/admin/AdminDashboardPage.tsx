import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api/http";
import {
  AdminUsage,
  AuditLogEntry,
  AuditLogResponse,
  LearningZone,
  ZoneNotebook,
} from "../api/types";
import { useAuth } from "../auth/useAuth";

interface ZoneEditorState {
  title: string;
  description: string;
}

export function AdminDashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const replaceInputRef = useRef<HTMLInputElement | null>(null);

  const [zones, setZones] = useState<LearningZone[]>([]);
  const [zoneNotebooks, setZoneNotebooks] = useState<Record<string, ZoneNotebook[]>>(
    {}
  );
  const [expandedZoneId, setExpandedZoneId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newZone, setNewZone] = useState<ZoneEditorState>({
    title: "",
    description: "",
  });
  const [editingZoneId, setEditingZoneId] = useState<string | null>(null);
  const [editingZone, setEditingZone] = useState<ZoneEditorState>({
    title: "",
    description: "",
  });

  const [newNotebookTitle, setNewNotebookTitle] = useState("");
  const [newNotebookDescription, setNewNotebookDescription] = useState("");
  const [newNotebookFile, setNewNotebookFile] = useState<File | null>(null);
  const [replaceNotebookId, setReplaceNotebookId] = useState<string | null>(null);

  // Usage and audit state.
  const [usage, setUsage] = useState<AdminUsage | null>(null);
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([]);
  const [auditPage, setAuditPage] = useState(1);
  const [auditTotalPages, setAuditTotalPages] = useState(1);

  useEffect(() => {
    if (user && !user.is_admin) {
      navigate("/chat", { replace: true });
    }
  }, [user, navigate]);

  const loadZones = async () => {
    try {
      const data = await apiFetch<LearningZone[]>("/api/admin/zones");
      setZones(data);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin zones.");
    } finally {
      setLoading(false);
    }
  };

  const loadZoneNotebooks = async (zoneId: string) => {
    try {
      const data = await apiFetch<ZoneNotebook[]>(
        `/api/admin/zones/${zoneId}/notebooks`
      );
      setZoneNotebooks((prev) => ({ ...prev, [zoneId]: data }));
      setError("");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load zone notebooks."
      );
    }
  };

  const loadUsage = async () => {
    try {
      const data = await apiFetch<AdminUsage>("/api/admin/usage");
      setUsage(data);
    } catch {
      // Usage is optional; do not block the page on failure.
    }
  };

  const loadAuditLog = async (page: number) => {
    try {
      const data = await apiFetch<AuditLogResponse>(
        `/api/admin/audit-log?page=${page}&per_page=20`
      );
      setAuditEntries(data.entries);
      setAuditTotalPages(data.total_pages);
      setAuditPage(data.page);
    } catch {
      // Audit log is optional.
    }
  };

  useEffect(() => {
    if (user?.is_admin) {
      void loadZones();
      void loadUsage();
      void loadAuditLog(1);
    }
  }, [user?.is_admin]);

  if (!user?.is_admin) {
    return null;
  }

  const toggleZone = async (zoneId: string) => {
    if (expandedZoneId === zoneId) {
      setExpandedZoneId(null);
      return;
    }
    setExpandedZoneId(zoneId);
    if (!zoneNotebooks[zoneId]) {
      await loadZoneNotebooks(zoneId);
    }
  };

  const handleCreateZone = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await apiFetch("/api/admin/zones", {
        method: "POST",
        body: JSON.stringify(newZone),
      });
      setShowCreateForm(false);
      setNewZone({ title: "", description: "" });
      await loadZones();
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create zone.");
    }
  };

  const handleDeleteZone = async (zoneId: string) => {
    const confirmed = window.confirm(
      "Delete this zone? All notebooks and student progress in this zone will be removed."
    );
    if (!confirmed) return;
    try {
      await apiFetch(`/api/admin/zones/${zoneId}`, { method: "DELETE" });
      setZones((items) => items.filter((item) => item.id !== zoneId));
      setExpandedZoneId((id) => (id === zoneId ? null : id));
      setZoneNotebooks((prev) => {
        const next = { ...prev };
        delete next[zoneId];
        return next;
      });
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete zone.");
    }
  };

  const startEditZone = (zone: LearningZone) => {
    setEditingZoneId(zone.id);
    setEditingZone({ title: zone.title, description: zone.description });
  };

  const handleSaveZoneEdit = async (zoneId: string) => {
    try {
      await apiFetch(`/api/admin/zones/${zoneId}`, {
        method: "PUT",
        body: JSON.stringify(editingZone),
      });
      setEditingZoneId(null);
      await loadZones();
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update zone.");
    }
  };

  const handleAddNotebook = async (event: FormEvent) => {
    event.preventDefault();
    if (!expandedZoneId || !newNotebookFile) return;

    const formData = new FormData();
    formData.append("title", newNotebookTitle);
    formData.append("description", newNotebookDescription);
    formData.append("file", newNotebookFile);

    try {
      await apiFetch(`/api/admin/zones/${expandedZoneId}/notebooks`, {
        method: "POST",
        body: formData,
      });
      setNewNotebookTitle("");
      setNewNotebookDescription("");
      setNewNotebookFile(null);
      await loadZoneNotebooks(expandedZoneId);
      await loadZones();
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add notebook.");
    }
  };

  const handleDeleteNotebook = async (notebookId: string) => {
    const confirmed = window.confirm(
      "Delete this notebook? All student progress for this notebook will be removed."
    );
    if (!confirmed || !expandedZoneId) return;

    try {
      await apiFetch(`/api/admin/notebooks/${notebookId}`, { method: "DELETE" });
      await loadZoneNotebooks(expandedZoneId);
      await loadZones();
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete notebook.");
    }
  };

  const triggerReplaceNotebook = (notebookId: string) => {
    setReplaceNotebookId(notebookId);
    replaceInputRef.current?.click();
  };

  const handleReplaceNotebook = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !replaceNotebookId || !expandedZoneId) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      await apiFetch(`/api/admin/notebooks/${replaceNotebookId}`, {
        method: "PUT",
        body: formData,
      });
      await loadZoneNotebooks(expandedZoneId);
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to replace notebook.");
    } finally {
      setReplaceNotebookId(null);
      if (replaceInputRef.current) {
        replaceInputRef.current.value = "";
      }
    }
  };

  const moveNotebook = async (zoneId: string, fromIndex: number, toIndex: number) => {
    const list = zoneNotebooks[zoneId] ?? [];
    if (toIndex < 0 || toIndex >= list.length) return;

    const next = [...list];
    const [item] = next.splice(fromIndex, 1);
    next.splice(toIndex, 0, item);

    setZoneNotebooks((prev) => ({ ...prev, [zoneId]: next }));
    try {
      await apiFetch(`/api/admin/zones/${zoneId}/notebooks/reorder`, {
        method: "PUT",
        body: JSON.stringify({ notebook_ids: next.map((n) => n.id) }),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reorder notebooks.");
      await loadZoneNotebooks(zoneId);
    }
  };

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
  };

  const formatDate = (iso: string | null) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-brand">Admin Dashboard</h1>
            <p className="mt-1 text-sm text-gray-600">
              Manage learning zones, view usage, and review audit history.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm((value) => !value)}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-brand hover:bg-accent-dark"
          >
            Create Zone
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Usage Overview */}
        {usage && (
          <div className="mb-6 grid gap-4 md:grid-cols-3">
            {(["today", "this_week", "this_month"] as const).map((period) => {
              const label = period === "today" ? "Today" : period === "this_week" ? "This Week" : "This Month";
              const data = usage[period];
              return (
                <div
                  key={period}
                  className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
                >
                  <h3 className="text-sm font-medium text-gray-500">{label}</h3>
                  <div className="mt-2 space-y-1">
                    <p className="text-sm text-gray-700">
                      Input: <span className="font-semibold">{formatTokens(data.input_tokens)}</span> tokens
                    </p>
                    <p className="text-sm text-gray-700">
                      Output: <span className="font-semibold">{formatTokens(data.output_tokens)}</span> tokens
                    </p>
                    <p className="text-sm font-medium text-brand">
                      Est. cost: ${data.estimated_cost_usd.toFixed(2)}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Audit Log */}
        {auditEntries.length > 0 && (
          <div className="mb-6 rounded-lg border border-gray-200 bg-white shadow-sm">
            <div className="border-b border-gray-100 px-4 py-3">
              <h2 className="text-sm font-semibold text-brand">Audit Log</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="px-4 py-2">Time</th>
                    <th className="px-4 py-2">Admin</th>
                    <th className="px-4 py-2">Action</th>
                    <th className="px-4 py-2">Resource</th>
                  </tr>
                </thead>
                <tbody>
                  {auditEntries.map((entry) => (
                    <tr key={entry.id} className="border-b border-gray-50">
                      <td className="px-4 py-2 text-gray-500">{formatDate(entry.created_at)}</td>
                      <td className="px-4 py-2 text-gray-700">{entry.admin_email}</td>
                      <td className="px-4 py-2">
                        <span
                          className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${
                            entry.action === "create"
                              ? "bg-green-50 text-green-700"
                              : entry.action === "delete"
                                ? "bg-red-50 text-red-700"
                                : "bg-blue-50 text-blue-700"
                          }`}
                        >
                          {entry.action}
                        </span>{" "}
                        <span className="text-gray-500">{entry.resource_type}</span>
                      </td>
                      <td className="px-4 py-2 text-gray-700">{entry.resource_title || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {auditTotalPages > 1 && (
              <div className="flex items-center justify-between border-t border-gray-100 px-4 py-2">
                <button
                  type="button"
                  disabled={auditPage <= 1}
                  onClick={() => void loadAuditLog(auditPage - 1)}
                  className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Previous
                </button>
                <span className="text-xs text-gray-500">
                  Page {auditPage} of {auditTotalPages}
                </span>
                <button
                  type="button"
                  disabled={auditPage >= auditTotalPages}
                  onClick={() => void loadAuditLog(auditPage + 1)}
                  className="rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}

        {showCreateForm && (
          <form
            onSubmit={handleCreateZone}
            className="mb-5 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
          >
            <div className="grid gap-3 md:grid-cols-2">
              <input
                type="text"
                value={newZone.title}
                onChange={(event) =>
                  setNewZone((prev) => ({ ...prev, title: event.target.value }))
                }
                placeholder="Zone title"
                className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                required
              />
              <input
                type="text"
                value={newZone.description}
                onChange={(event) =>
                  setNewZone((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                placeholder="Zone description"
                className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                required
              />
            </div>
            <div className="mt-3 flex gap-2">
              <button
                type="submit"
                className="rounded-md bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-light"
              >
                Save Zone
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        <input
          ref={replaceInputRef}
          type="file"
          accept=".ipynb"
          className="hidden"
          onChange={handleReplaceNotebook}
        />

        {loading ? (
          <div className="rounded-lg bg-white p-8 text-center text-gray-500">
            Loading admin data...
          </div>
        ) : zones.length === 0 ? (
          <div className="rounded-lg bg-white p-8 text-center text-gray-500">
            No learning zones yet.
          </div>
        ) : (
          <div className="space-y-4">
            {zones.map((zone) => {
              const isExpanded = expandedZoneId === zone.id;
              const notebooks = zoneNotebooks[zone.id] ?? [];

              return (
                <section
                  key={zone.id}
                  className="rounded-lg border border-gray-200 bg-white shadow-sm"
                >
                  <div className="flex items-start justify-between gap-4 p-4">
                    {editingZoneId === zone.id ? (
                      <div className="flex-1 space-y-2">
                        <input
                          type="text"
                          value={editingZone.title}
                          onChange={(event) =>
                            setEditingZone((prev) => ({
                              ...prev,
                              title: event.target.value,
                            }))
                          }
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                        />
                        <textarea
                          value={editingZone.description}
                          onChange={(event) =>
                            setEditingZone((prev) => ({
                              ...prev,
                              description: event.target.value,
                            }))
                          }
                          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                          rows={3}
                        />
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => void handleSaveZoneEdit(zone.id)}
                            className="rounded-md bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-light"
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingZoneId(null)}
                            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1">
                        <h2 className="text-lg font-semibold text-brand">{zone.title}</h2>
                        <p className="mt-1 text-sm text-gray-600">{zone.description}</p>
                        <p className="mt-2 text-xs text-gray-500">
                          {zone.notebook_count} notebook
                          {zone.notebook_count === 1 ? "" : "s"}
                        </p>
                      </div>
                    )}

                    {editingZoneId !== zone.id && (
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => startEditZone(zone)}
                          className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteZone(zone.id)}
                          className="rounded-md border border-red-200 px-2.5 py-1 text-xs text-red-600 hover:bg-red-50"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => void toggleZone(zone.id)}
                          className="rounded-md border border-gray-300 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-50"
                        >
                          {isExpanded ? "Hide Notebooks" : "Manage Notebooks"}
                        </button>
                      </div>
                    )}
                  </div>

                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-4">
                      <form
                        onSubmit={handleAddNotebook}
                        className="mb-4 rounded-md border border-gray-200 bg-gray-50 p-3"
                      >
                        <p className="mb-2 text-sm font-medium text-brand">Add Notebook</p>
                        <div className="grid gap-2 md:grid-cols-3">
                          <input
                            type="text"
                            placeholder="Title"
                            value={newNotebookTitle}
                            onChange={(event) => setNewNotebookTitle(event.target.value)}
                            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                            required
                          />
                          <input
                            type="text"
                            placeholder="Description (optional)"
                            value={newNotebookDescription}
                            onChange={(event) =>
                              setNewNotebookDescription(event.target.value)
                            }
                            className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                          />
                          <input
                            type="file"
                            accept=".ipynb"
                            onChange={(event) =>
                              setNewNotebookFile(event.target.files?.[0] ?? null)
                            }
                            className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                            required
                          />
                        </div>
                        <button
                          type="submit"
                          className="mt-2 rounded-md bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-light"
                        >
                          Upload Notebook
                        </button>
                      </form>

                      {notebooks.length === 0 ? (
                        <p className="text-sm text-gray-500">No notebooks in this zone.</p>
                      ) : (
                        <div className="space-y-2">
                          {notebooks.map((notebook, index) => (
                            <div
                              key={notebook.id}
                              className="flex items-center justify-between gap-3 rounded-md border border-gray-200 bg-white px-3 py-2"
                            >
                              <div>
                                <p className="text-sm font-medium text-brand">
                                  {notebook.title}
                                </p>
                                {notebook.description && (
                                  <p className="text-xs text-gray-600">
                                    {notebook.description}
                                  </p>
                                )}
                              </div>

                              <div className="flex gap-1">
                                <button
                                  type="button"
                                  onClick={() =>
                                    void moveNotebook(zone.id, index, index - 1)
                                  }
                                  className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                                  disabled={index === 0}
                                >
                                  ↑
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    void moveNotebook(zone.id, index, index + 1)
                                  }
                                  className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                                  disabled={index === notebooks.length - 1}
                                >
                                  ↓
                                </button>
                                <button
                                  type="button"
                                  onClick={() => triggerReplaceNotebook(notebook.id)}
                                  className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50"
                                >
                                  Replace
                                </button>
                                <button
                                  type="button"
                                  onClick={() => void handleDeleteNotebook(notebook.id)}
                                  className="rounded-md border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
                                >
                                  Delete
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
