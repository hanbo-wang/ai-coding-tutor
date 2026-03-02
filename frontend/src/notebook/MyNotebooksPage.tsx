import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../api/http";
import { NotebookSummary } from "../api/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function MyNotebooksPage() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [error, setError] = useState("");

  const loadNotebooks = async () => {
    try {
      const list = await apiFetch<NotebookSummary[]>("/api/notebooks");
      setNotebooks(list);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load notebooks.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadNotebooks();
  }, []);

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    setIsUploading(true);
    setError("");
    try {
      await apiFetch("/api/notebooks", { method: "POST", body: formData });
      await loadNotebooks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setIsUploading(false);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  };

  const handleDelete = async (id: string) => {
    const confirmed = window.confirm(
      "Delete this notebook and all related chat history? This action cannot be undone."
    );
    if (!confirmed) return;

    try {
      await apiFetch(`/api/notebooks/${id}`, { method: "DELETE" });
      setNotebooks((items) => items.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    }
  };

  const startRename = (notebook: NotebookSummary) => {
    setRenamingId(notebook.id);
    setRenameValue(notebook.title);
    setError("");
  };

  const cancelRename = () => {
    setRenamingId(null);
    setRenameValue("");
  };

  const saveRename = async (id: string) => {
    const nextTitle = renameValue.trim();
    if (!nextTitle) {
      setError("Notebook title cannot be empty.");
      return;
    }

    setIsRenaming(true);
    setError("");
    try {
      const updated = await apiFetch<NotebookSummary>(`/api/notebooks/${id}/rename`, {
        method: "PATCH",
        body: JSON.stringify({ title: nextTitle }),
      });
      setNotebooks((items) =>
        items.map((item) => (item.id === id ? updated : item))
      );
      cancelRename();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Rename failed.");
    } finally {
      setIsRenaming(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-gray-100">
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-brand">My Notebooks</h1>
            <p className="text-sm text-gray-600 mt-1">
              Upload your `.ipynb` files and learn with notebook-aware AI help.
            </p>
          </div>
          <div>
            <input
              ref={inputRef}
              type="file"
              accept=".ipynb"
              className="hidden"
              onChange={handleUpload}
            />
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={isUploading}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-brand hover:bg-accent-dark disabled:opacity-60"
            >
              {isUploading ? "Uploading..." : "Upload Notebook"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {isLoading ? (
          <div className="rounded-lg border border-gray-200 bg-white p-10 text-center text-gray-500">
            Loading notebooks...
          </div>
        ) : notebooks.length === 0 ? (
          <div className="rounded-lg border border-dashed border-gray-300 bg-white p-10 text-center">
            <p className="text-gray-600">
              No notebooks yet. Upload an `.ipynb` file to start your workspace.
            </p>
          </div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {notebooks.map((notebook) => (
              <article
                key={notebook.id}
                className="rounded-lg border border-gray-200 bg-white p-5 shadow-sm"
              >
                {renamingId === notebook.id ? (
                  <input
                    type="text"
                    value={renameValue}
                    onChange={(event) => setRenameValue(event.target.value)}
                    className="w-full rounded-md border border-gray-300 px-2.5 py-1.5 text-base font-semibold text-brand focus:border-accent focus:outline-none"
                    maxLength={120}
                    autoFocus
                  />
                ) : (
                  <h2 className="truncate text-lg font-semibold text-brand">
                    {notebook.title}
                  </h2>
                )}
                <p className="mt-1 truncate text-sm text-gray-600">
                  {notebook.original_filename}
                </p>
                <p className="mt-2 text-xs text-gray-500">
                  {formatSize(notebook.size_bytes)} • Uploaded{" "}
                  {new Date(notebook.created_at).toLocaleDateString()}
                </p>

                <div className="mt-4 flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/notebook/${notebook.id}`)}
                    className="rounded-md bg-brand px-3 py-1.5 text-sm text-white hover:bg-brand-light"
                  >
                    Open
                  </button>
                  {renamingId === notebook.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => void saveRename(notebook.id)}
                        disabled={isRenaming}
                        className="rounded-md border border-blue-200 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-60"
                      >
                        {isRenaming ? "Saving..." : "Save"}
                      </button>
                      <button
                        type="button"
                        onClick={cancelRename}
                        disabled={isRenaming}
                        className="rounded-md border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => startRename(notebook)}
                      className="rounded-md border border-blue-200 px-3 py-1.5 text-sm text-blue-700 hover:bg-blue-50"
                    >
                      Rename
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleDelete(notebook.id)}
                    disabled={isRenaming && renamingId === notebook.id}
                    className="rounded-md border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 disabled:opacity-60"
                  >
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
