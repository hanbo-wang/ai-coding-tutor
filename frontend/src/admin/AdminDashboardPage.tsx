import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api/http";
import {
  AdminUsage,
  AuditLogEntry,
  AuditLogResponse,
  LearningZone,
  ZoneImportResult,
  ZoneNotebook,
  ZoneSharedFile,
} from "../api/types";
import { useAuth } from "../auth/useAuth";

interface ZoneEditorState {
  title: string;
  description: string;
}

interface NotebookEditorState {
  title: string;
  description: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function AdminDashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const replaceInputRef = useRef<HTMLInputElement | null>(null);
  const assetsFileInputRef = useRef<HTMLInputElement | null>(null);
  const assetsFolderInputRef = useRef<HTMLInputElement | null>(null);

  const [zones, setZones] = useState<LearningZone[]>([]);
  const [zoneNotebooks, setZoneNotebooks] = useState<Record<string, ZoneNotebook[]>>(
    {}
  );
  const [zoneSharedFiles, setZoneSharedFiles] = useState<
    Record<string, ZoneSharedFile[]>
  >({});
  const [expandedZoneId, setExpandedZoneId] = useState<string | null>(null);
  const [assetTargetZoneId, setAssetTargetZoneId] = useState<string | null>(null);

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

  const [replaceNotebookId, setReplaceNotebookId] = useState<string | null>(null);
  const [editingNotebookId, setEditingNotebookId] = useState<string | null>(null);
  const [editingNotebook, setEditingNotebook] = useState<NotebookEditorState>({
    title: "",
    description: "",
  });

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
      const data = await apiFetch<ZoneNotebook[]>(`/api/admin/zones/${zoneId}/notebooks`);
      setZoneNotebooks((prev) => ({ ...prev, [zoneId]: data }));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load zone notebooks.");
    }
  };

  const loadZoneSharedFiles = async (zoneId: string) => {
    try {
      const data = await apiFetch<ZoneSharedFile[]>(
        `/api/admin/zones/${zoneId}/shared-files`
      );
      setZoneSharedFiles((prev) => ({ ...prev, [zoneId]: data }));
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load shared files.");
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
    if (!zoneNotebooks[zoneId] || !zoneSharedFiles[zoneId]) {
      await Promise.all([loadZoneNotebooks(zoneId), loadZoneSharedFiles(zoneId)]);
    }
  };

  const handleCreateZone = async (event: FormEvent) => {
    event.preventDefault();
    const title = newZone.title.trim();
    if (!title) {
      setError("Zone title cannot be empty.");
      return;
    }

    try {
      await apiFetch("/api/admin/zones", {
        method: "POST",
        body: JSON.stringify({
          title,
          description: newZone.description.trim() || null,
        }),
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
      setZoneSharedFiles((prev) => {
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
    setEditingZone({ title: zone.title, description: zone.description ?? "" });
  };

  const handleSaveZoneEdit = async (zoneId: string) => {
    const title = editingZone.title.trim();
    if (!title) {
      setError("Zone title cannot be empty.");
      return;
    }

    try {
      await apiFetch(`/api/admin/zones/${zoneId}`, {
        method: "PUT",
        body: JSON.stringify({
          title,
          description: editingZone.description.trim() || null,
        }),
      });
      setEditingZoneId(null);
      await loadZones();
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update zone.");
    }
  };

  const openAssetsFilePicker = (zoneId: string) => {
    setAssetTargetZoneId(zoneId);
    assetsFileInputRef.current?.click();
  };

  const openAssetsFolderPicker = (zoneId: string) => {
    setAssetTargetZoneId(zoneId);
    const input = assetsFolderInputRef.current;
    if (!input) return;
    input.setAttribute("webkitdirectory", "");
    input.setAttribute("directory", "");
    input.click();
  };

  const handleImportAssets = async (event: ChangeEvent<HTMLInputElement>) => {
    const zoneId = assetTargetZoneId;
    const files = Array.from(event.target.files ?? []);
    if (!zoneId || files.length === 0) {
      event.target.value = "";
      setAssetTargetZoneId(null);
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
      const relativePath = (
        file as File & {
          webkitRelativePath?: string;
        }
      ).webkitRelativePath;
      formData.append("relative_paths", relativePath || file.name);
    }

    try {
      const result = await apiFetch<ZoneImportResult>(
        `/api/admin/zones/${zoneId}/assets`,
        {
          method: "POST",
          body: formData,
        }
      );
      if (
        result.notebooks_created === 0 &&
        result.shared_files_created === 0 &&
        result.shared_files_updated === 0
      ) {
        setError("No files were imported.");
      } else {
        setError("");
      }
      await Promise.all([loadZoneNotebooks(zoneId), loadZoneSharedFiles(zoneId), loadZones()]);
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import assets.");
    } finally {
      event.target.value = "";
      setAssetTargetZoneId(null);
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

  const startEditNotebook = (notebook: ZoneNotebook) => {
    setEditingNotebookId(notebook.id);
    setEditingNotebook({
      title: notebook.title,
      description: notebook.description ?? "",
    });
  };

  const handleSaveNotebookMetadata = async (notebookId: string) => {
    const title = editingNotebook.title.trim();
    if (!title) {
      setError("Notebook title cannot be empty.");
      return;
    }

    try {
      await apiFetch(`/api/admin/notebooks/${notebookId}/metadata`, {
        method: "PATCH",
        body: JSON.stringify({
          title,
          description: editingNotebook.description.trim() || null,
        }),
      });
      setEditingNotebookId(null);
      if (expandedZoneId) {
        await loadZoneNotebooks(expandedZoneId);
      }
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update notebook.");
    }
  };

  const handleDeleteSharedFile = async (sharedFileId: string) => {
    const confirmed = window.confirm(
      "Delete this shared dependency file from the zone?"
    );
    if (!confirmed || !expandedZoneId) return;

    try {
      await apiFetch(`/api/admin/shared-files/${sharedFileId}`, { method: "DELETE" });
      await loadZoneSharedFiles(expandedZoneId);
      await loadAuditLog(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete shared file.");
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

  const panelSection =
    "rounded-md border border-gray-200 bg-gray-50 p-4";
  const sectionTitle = "text-sm font-semibold text-brand";
  const sectionHint = "text-xs leading-5 text-gray-600";
  const inputBase =
    "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30";
  const btnPrimary =
    "inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-brand transition-colors hover:bg-accent-dark focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60";
  const btnSecondary =
    "inline-flex h-9 items-center justify-center rounded-md border border-gray-300 bg-white px-4 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-60";
  const btnDanger =
    "inline-flex h-9 items-center justify-center rounded-md border border-red-200 bg-white px-4 text-sm font-medium text-red-600 transition-colors hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-200 disabled:cursor-not-allowed disabled:opacity-60";
  const btnIcon =
    "inline-flex h-8 w-8 items-center justify-center rounded-md border border-gray-300 bg-white text-xs font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-60";

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-brand">Admin Dashboard</h1>
            <p className="mt-1 text-sm text-gray-600">
              Manage learning zones, notebooks, shared dependencies, usage, and audit history.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreateForm((value) => !value)}
            className={btnPrimary}
          >
            Create Zone
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {usage && (
          <div className="mb-6 grid gap-4 md:grid-cols-3">
            {(["today", "this_week", "this_month"] as const).map((period) => {
              const label =
                period === "today"
                  ? "Today"
                  : period === "this_week"
                    ? "This Week"
                    : "This Month";
              const data = usage[period];
              return (
                <div
                  key={period}
                  className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
                >
                  <h3 className="text-sm font-medium text-gray-500">{label}</h3>
                  <div className="mt-2 space-y-1">
                    <p className="text-sm text-gray-700">
                      Input: <span className="font-semibold">{formatTokens(data.input_tokens)}</span>{" "}
                      tokens
                    </p>
                    <p className="text-sm text-gray-700">
                      Output: <span className="font-semibold">{formatTokens(data.output_tokens)}</span>{" "}
                      tokens
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
                  className={`${btnSecondary} h-7 px-2 text-xs`}
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
                  className={`${btnSecondary} h-7 px-2 text-xs`}
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
                placeholder="Zone description (optional)"
                className="rounded-md border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="mt-3 flex gap-2">
              <button
                type="submit"
                className={btnPrimary}
              >
                Save Zone
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className={btnSecondary}
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

        <input
          ref={assetsFileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleImportAssets}
        />

        <input
          ref={assetsFolderInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleImportAssets}
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
              const sharedFiles = zoneSharedFiles[zone.id] ?? [];

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
                            className={btnPrimary}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            onClick={() => setEditingZoneId(null)}
                            className={btnSecondary}
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1">
                        <h2 className="text-lg font-semibold text-brand">{zone.title}</h2>
                        <p className="mt-1 text-sm text-gray-600">
                          {zone.description || "No description yet."}
                        </p>
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
                          className={`${btnSecondary} h-8 px-3 text-xs`}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDeleteZone(zone.id)}
                          className={`${btnDanger} h-8 px-3 text-xs`}
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => void toggleZone(zone.id)}
                          className={`${btnSecondary} h-8 px-3 text-xs`}
                        >
                          {isExpanded ? "Hide Details" : "Manage Zone"}
                        </button>
                      </div>
                    )}
                  </div>

                  {isExpanded && (
                    <div className="border-t border-gray-100 px-4 py-4">
                      <div className="space-y-4">
                        <div className={panelSection}>
                          <p className={sectionTitle}>Import Folder / Shared Files</p>
                          <p className={`mt-2 ${sectionHint}`}>
                            If imported files include `.ipynb`, they will be auto-created as
                            notebooks. Other files become shared dependencies for all notebooks in
                            this zone.
                          </p>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => openAssetsFolderPicker(zone.id)}
                              className={btnSecondary}
                            >
                              Upload Folder
                            </button>
                            <button
                              type="button"
                              onClick={() => openAssetsFilePicker(zone.id)}
                              className={btnSecondary}
                            >
                              Upload Files
                            </button>
                          </div>
                        </div>

                        {notebooks.length === 0 ? (
                          <p className="px-1 text-sm text-gray-500">No notebooks in this zone.</p>
                        ) : (
                          <div className="space-y-2">
                            {notebooks.map((notebook, index) => (
                              <div
                                key={notebook.id}
                                className="rounded-md border border-gray-200 bg-white p-3"
                              >
                                {editingNotebookId === notebook.id ? (
                                  <div className="space-y-2">
                                    <input
                                      type="text"
                                      value={editingNotebook.title}
                                      onChange={(event) =>
                                        setEditingNotebook((prev) => ({
                                          ...prev,
                                          title: event.target.value,
                                        }))
                                      }
                                      className={inputBase}
                                    />
                                    <textarea
                                      value={editingNotebook.description}
                                      onChange={(event) =>
                                        setEditingNotebook((prev) => ({
                                          ...prev,
                                          description: event.target.value,
                                        }))
                                      }
                                      className={inputBase}
                                      rows={2}
                                    />
                                    <div className="flex flex-wrap gap-2">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          void handleSaveNotebookMetadata(notebook.id)
                                        }
                                        className={btnPrimary}
                                      >
                                        Save
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => setEditingNotebookId(null)}
                                        className={btnSecondary}
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0">
                                      <p className="truncate text-sm font-medium text-brand">
                                        {notebook.title}
                                      </p>
                                      <p className="mt-0.5 text-xs text-gray-600">
                                        {notebook.description || "No description"}
                                      </p>
                                    </div>

                                    <div className="flex flex-wrap items-center justify-end gap-1.5">
                                      <button
                                        type="button"
                                        onClick={() =>
                                          void moveNotebook(zone.id, index, index - 1)
                                        }
                                        className={btnIcon}
                                        disabled={index === 0}
                                      >
                                        ↑
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() =>
                                          void moveNotebook(zone.id, index, index + 1)
                                        }
                                        className={btnIcon}
                                        disabled={index === notebooks.length - 1}
                                      >
                                        ↓
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => startEditNotebook(notebook)}
                                        className={`${btnSecondary} h-8 px-3 text-xs`}
                                      >
                                        Edit
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => triggerReplaceNotebook(notebook.id)}
                                        className={`${btnSecondary} h-8 px-3 text-xs`}
                                      >
                                        Replace
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => void handleDeleteNotebook(notebook.id)}
                                        className={`${btnDanger} h-8 px-3 text-xs`}
                                      >
                                        Delete
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                        <div className={panelSection}>
                          <p className={sectionTitle}>Shared Dependency Files (Admin Only)</p>
                          <p className={`mt-2 ${sectionHint}`}>
                            Students do not see this list. These files are injected into each zone
                            notebook runtime.
                          </p>
                          {sharedFiles.length === 0 ? (
                            <p className="mt-3 text-sm text-gray-500">No shared files yet.</p>
                          ) : (
                            <div className="mt-3 space-y-2">
                              {sharedFiles.map((item) => (
                                <div
                                  key={item.id}
                                  className="flex items-center justify-between gap-3 rounded-md border border-gray-200 bg-white px-3 py-2"
                                >
                                  <div className="min-w-0">
                                    <p className="truncate text-xs font-medium text-brand">
                                      {item.relative_path}
                                    </p>
                                    <p className="text-[11px] text-gray-600">
                                      {formatSize(item.size_bytes)}
                                    </p>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => void handleDeleteSharedFile(item.id)}
                                    className={`${btnDanger} h-8 px-3 text-xs`}
                                  >
                                    Delete
                                  </button>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
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
