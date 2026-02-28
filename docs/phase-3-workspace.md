# Phase 3: Notebook Workspace and Learning Hub

**Prerequisite:** Phase 2 complete (chat, pedagogy engine, and uploads working).

**Visible result:** Students can upload notebooks, run Python in-browser with JupyterLite, and chat with a tutor in the same split workspace. Admins can manage zones, notebooks, and shared dependency files in a Learning Hub, and each student keeps an independent progress copy.

---

## 1. What This Phase Delivers

### Part A: Personal Notebook Workspace

- User notebook storage with strict ownership checks.
- Notebook upload, list, open, save, rename, and delete APIs.
- A split workspace page: notebook on the left, tutor chat on the right.
- A JupyterLite bridge (`postMessage`) for loading notebooks and reading live cell context.
- Scoped chat sessions per notebook, so notebook chats do not mix with general chats.
- Layered save behaviour: in-browser autosave, dirty-checked backend sync, and a final keepalive flush on page leave.

### Part B: Admin Learning Hub

- Admin role support (`is_admin`) driven by `ADMIN_EMAIL`.
- Learning zones and zone notebook management (admin API and dashboard), with optional descriptions.
- Zone asset import from files or folders, with `.ipynb` files auto-created as notebooks.
- Zone shared dependency files, injected into zone notebook runtime and managed by admins.
- Student-facing zone pages show notebooks only; shared dependency files remain admin-only.
- Public zone browsing for all authenticated users.
- Per-user zone notebook progress (`zone_notebook_progress`) with reset-to-original.
- Scoped chat sessions per zone notebook.

---

## 2. End-to-End Architecture

1. Student opens `/notebook/:notebookId` or `/zone-notebook/:zoneId/:notebookId`.
2. `NotebookPanel` loads the JupyterLite iframe and waits for bridge readiness.
3. Backend returns notebook JSON (personal state or zone progress/original).
4. In zone workspace mode, frontend fetches runtime dependency files from `/api/zones/{zone_id}/notebooks/{notebook_id}/runtime-files`.
5. Frontend sends `load-notebook` to iframe bridge with a scoped workspace key and `workspace_files`.
6. Student edits and runs code; bridge emits `notebook-dirty` events.
7. JupyterLite saves in-browser, while frontend syncs to backend only when dirty.
8. Tutor chat sends scoped identifiers (`notebook_id` or `zone_notebook_id`) plus current cell code and error output.
9. Backend injects notebook context into the system prompt and stores messages in a scoped session.

---

## 3. JupyterLite Setup and Bridge

### 3.1 Build Script

**Script:** `scripts/build-jupyterlite.sh`

Installs `jupyterlite-core`, `jupyterlite-pyodide-kernel`, and `jupyterlab`. Builds the bridge extension from `jupyterlite-bridge/`, then builds JupyterLite into `frontend/public/jupyterlite/`. The script patches `jupyter-lite.json` for workspace settings (autosave every 12s, no close confirmation, no recents) and verifies the bridge extension is registered.

The output directory is git-ignored as a generated artefact.

### 3.2 Bridge Extension

**Directory:** `jupyterlite-bridge/`

A `JupyterFrontEndPlugin` with `autoStart: true`, packaged as a labextension.

| Command                     | Direction        | Purpose                                               |
| --------------------------- | ---------------- | ----------------------------------------------------- |
| `ping`                    | Parent to iframe | Health check for bridge readiness.                    |
| `ready`                   | Iframe to parent | Bridge ready signal (sent multiple times on startup). |
| `load-notebook`           | Parent to iframe | Save/open notebook payload and inject `workspace_files`. |
| `get-notebook-state`      | Parent to iframe | Return full current notebook JSON.                    |
| `get-current-cell`        | Parent to iframe | Return active cell source and index.                  |
| `get-error-output`        | Parent to iframe | Return latest error traceback text if present.        |
| `notebook-dirty`          | Iframe to parent | Notify that notebook content changed.                 |
| `notebook-save-requested` | Iframe to parent | Notify that user triggered manual save in Jupyter UI. |

### 3.3 Kernel and Package Defaults

Kernel display name: `Numerical Computing`. Preloaded Pyodide packages: numpy, scipy, pandas, matplotlib, sympy.

### 3.4 Single-Notebook Workspace Isolation

The bridge enforces single-document behaviour: forces single-document shell mode, hides sidebars and status bar, disposes unrelated widgets, deletes other notebook files, shuts down unrelated sessions, and clears recent documents. It generates a title-based filename so JupyterLab shows the title in the tab, and overrides download to use the display title.

---

## 4. Backend Implementation

### 4.1 Migrations and Data Model

**Migration `004`** adds `user_notebooks` for personal notebooks (ownership, metadata, storage info, current state, extracted context).

**Migration `005`** adds `users.is_admin`, `learning_zones`, `zone_notebooks`, `zone_shared_files`, and `zone_notebook_progress` (unique on `user_id, zone_notebook_id`). Zone and notebook descriptions are optional.

**Migration `006`** adds a partial unique index on `chat_sessions` for `(user_id, session_type, module_id)` when `session_type IN ('notebook', 'zone')` and `module_id IS NOT NULL`.

### 4.2 Notebook Storage Layout

Root storage from `NOTEBOOK_STORAGE_DIR` (default `/tmp/ai_coding_tutor_notebooks`). Personal notebooks: `<root>/<normalised_user_email>/`. Admin zone content: `<root>/learning_zone_notebooks/<zone_id>/notebooks` and `.../shared`. Shared zone files keep their relative paths and are served as `workspace_files` for zone notebook runtime.

### 4.3 Personal Notebook Service and API

**Service:** `backend/app/services/notebook_service.py` validates `.ipynb` extension and JSON structure, enforces notebook count and file size limits, persists notebook file and JSON state, refreshes extracted text, and handles rename.

**Router:** `backend/app/routers/notebooks.py`

| Endpoint                                | Method | Behaviour                                  |
| --------------------------------------- | ------ | ------------------------------------------ |
| `/api/notebooks`                      | GET    | List current user's notebooks.             |
| `/api/notebooks`                      | POST   | Upload notebook (`multipart/form-data`). |
| `/api/notebooks/{notebook_id}`        | GET    | Get notebook detail with JSON.             |
| `/api/notebooks/{notebook_id}`        | PUT    | Save current notebook JSON.                |
| `/api/notebooks/{notebook_id}`        | DELETE | Delete notebook and stored file.           |
| `/api/notebooks/{notebook_id}/rename` | PATCH  | Rename notebook title.                     |

### 4.4 Learning Zone and Admin APIs

**Zone router:** `backend/app/routers/zones.py`

| Endpoint                                                  | Method | Behaviour                                         |
| --------------------------------------------------------- | ------ | ------------------------------------------------- |
| `/api/zones`                                            | GET    | List zones for authenticated users.               |
| `/api/zones/{zone_id}`                                  | GET    | Zone detail + notebook list + `has_progress`.   |
| `/api/zones/{zone_id}/notebooks/{notebook_id}`          | GET    | Return notebook JSON (progress copy or original). |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/runtime-files` | GET    | Return runtime dependency files for zone notebook execution. |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/progress` | PUT    | Save user's progress notebook state.              |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/progress` | DELETE | Reset user's progress to original.                |

**Admin router:** `backend/app/routers/admin.py` (all endpoints require `get_admin_user`, all mutations log to `admin_audit_log`)

| Endpoint                                         | Method | Behaviour                                 |
| ------------------------------------------------ | ------ | ----------------------------------------- |
| `/api/admin/zones`                             | GET    | List zones with notebook counts.          |
| `/api/admin/zones`                             | POST   | Create zone.                              |
| `/api/admin/zones/{zone_id}`                   | PUT    | Update zone fields.                       |
| `/api/admin/zones/{zone_id}`                   | DELETE | Delete zone and related data.             |
| `/api/admin/zones/{zone_id}/notebooks`         | GET    | List notebooks in zone.                   |
| `/api/admin/zones/{zone_id}/notebooks`         | POST   | Upload notebook to zone.                  |
| `/api/admin/zones/{zone_id}/assets`            | POST   | Import files/folders; `.ipynb` auto-create notebooks, others become shared files. |
| `/api/admin/zones/{zone_id}/shared-files`      | GET    | List shared zone files.                   |
| `/api/admin/notebooks/{notebook_id}/metadata`  | PATCH  | Update zone notebook title and optional description. |
| `/api/admin/notebooks/{notebook_id}`           | PUT    | Replace notebook content.                 |
| `/api/admin/shared-files/{shared_file_id}`     | DELETE | Delete shared zone file.                  |
| `/api/admin/notebooks/{notebook_id}`           | DELETE | Delete zone notebook.                     |
| `/api/admin/zones/{zone_id}/notebooks/reorder` | PUT    | Reorder notebooks.                        |
| `/api/admin/llm/models`                        | GET    | Return current active LLM and available switch options with pricing. |
| `/api/admin/llm/switch`                        | POST   | Switch active LLM after admin password confirmation. |
| `/api/admin/audit-log`                         | GET    | Return paginated admin audit log entries. |
| `/api/admin/usage/by-model`                    | GET    | Return usage and estimated cost for one selected provider/model. |

### 4.5 Notebook-Aware and Scoped Chat

`ChatMessageIn` supports `notebook_id`, `zone_notebook_id`, `cell_code`, and `error_output`. The chat router accepts only one notebook scope per message, builds notebook context for the system prompt, and uses scoped `session_type` values (`general`, `notebook`, `zone`). It reuses a provided `session_id` only when it matches the current scope. General sidebar returns only `general` sessions; `/api/chat/sessions/find` handles scoped session restore.

The chat service resolves and reuses scoped sessions, validates scope matching, and handles unique-index races with `IntegrityError` fallback lookup.

### 4.6 Admin Email Rules

`ADMIN_EMAIL` in config supports comma, space, and semicolon separators, plus JSON array strings. On registration, matching emails get `is_admin=True`. On startup, existing matching users are promoted.

---

## 5. Frontend Implementation

### 5.1 Routes and Navigation

Routes: `/my-notebooks`, `/notebook/:notebookId`, `/learning-hub`, `/zones/:zoneId`, `/zone-notebook/:zoneId/:notebookId`, `/admin`, `/health`.

Navbar shows Chat, My Notebooks, Learning Hub, Profile for logged-in users, and Admin when `user.is_admin`.

### 5.2 My Notebooks Page

**`frontend/src/notebook/MyNotebooksPage.tsx`:** Upload `.ipynb`, open notebook workspace, rename, and delete. Notebook cards show title, filename, size, and upload date.

### 5.3 Notebook Workspace Panel

**`frontend/src/workspace/NotebookPanel.tsx`:** Loads `/jupyterlite/lab/index.html` in an iframe with cache-busting. Waits for bridge readiness via `ping` polling, then loads notebook JSON via `load-notebook`. In zone mode, fetches and passes `workspace_files`. Bridge performs local in-browser save with 5s debounce; frontend syncs to backend every 30s when dirty, immediately on manual save, and once on `beforeunload`/`pagehide`. Reports save status.

### 5.4 Workspace Chat Panel

**`frontend/src/workspace/WorkspaceChatPanel.tsx`:** Resolves scoped session via `/api/chat/sessions/find`, restores scoped message history, sends messages with notebook scope and live cell/error context. Provides `New chat` button that deletes the current scoped session. Workspace pages key the chat panel by scope so route changes remount and close the previous WebSocket.

### 5.5 Zone Notebook Workspace

**`frontend/src/workspace/ZoneNotebookWorkspacePage.tsx`:** Uses zone notebook endpoints, sends `zone_notebook_id` in chat scope, loads zone runtime dependency files, shows `Reset to Original` button. Shared dependency files are shown in admin dashboard only, not in student zone pages.

### 5.6 Admin Dashboard

**`frontend/src/admin/AdminDashboardPage.tsx`:** Zone CRUD with optional descriptions, file/folder import, shared file management, notebook metadata editing, notebook replace/delete/reorder, total usage panel, selected-model usage panel, and an LLM switch panel at the top. The model switch flow shows current model, available smoke-tested options, per-model input/output pricing, and requires the admin password before applying changes. Links to the frontend `/health` page for model diagnostics.

### 5.7 Split Layout

Uses the official `react-split` package for personal and zone workspace pages.

---

## 6. Verification Checklist

- [ ] `bash scripts/build-jupyterlite.sh` completes and the bridge extension is registered.
- [ ] `cd frontend && npm install && npm run build` succeeds.
- [ ] Upload a personal notebook, open it, edit, and refresh: state persists.
- [ ] Rename a notebook in My Notebooks: title and filename display update.
- [ ] Click Save in Jupyter UI: workspace status returns to `Saved` quickly.
- [ ] Open two different notebook routes in sequence: workspace shows only the active notebook.
- [ ] Leave notebook route and re-enter: no `Save your work` close dialog appears.
- [ ] Open a Learning Hub notebook as two different users: progress stays isolated.
- [ ] Import a folder containing `.ipynb` and dependency files: notebooks are auto-created and non-`.ipynb` files are stored as shared zone files.
- [ ] In zone workspace, imported shared files are available to notebook runtime imports.
- [ ] Shared zone files are manageable in admin dashboard and are not shown in student zone pages.
- [ ] Rename a zone or zone notebook in admin dashboard: audit log entry includes change details.
- [ ] Switching the active LLM in admin dashboard requires the admin password and shows a success message.
- [ ] Click `New chat` in workspace chat: scoped history resets for that notebook only.
- [ ] Switch between two notebook routes and send a message immediately after the page loads: the message is stored in the active notebook's scoped chat session only.
- [ ] Click `Reset to Original` in zone workspace: user progress is removed and original content reloads.

---

## 7. Known Constraints

- JupyterLite runs in browser WebAssembly, so performance is slower than native Python.
- Browser memory limits apply to large notebook workloads.
- Python packages are limited to what Pyodide can load.
- The notebook runtime is client-side; backend persists state but does not execute notebook code.
