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

The script currently does the following:

1. Installs required Python tooling:
   - `jupyterlite-core`
   - `jupyterlite-pyodide-kernel`
   - `jupyterlab`
2. Builds the bridge extension:
   - `cd jupyterlite-bridge`
   - `npm install`
   - `npm run build`
3. Builds JupyterLite in a temporary Linux directory (to reduce `/mnt/*` I/O stalls).
4. Injects the built lab extension from `jupyterlite-bridge/labextension/`.
5. Generates `frontend/public/jupyterlite/`.
6. Patches generated `jupyter-lite.json` files to enforce workspace settings.
7. Verifies `jupyterlite-bridge` is registered in `federated_extensions`; build fails if missing.

Current `docmanager` patch values:

- `autosave: true`
- `autosaveInterval: 12` seconds
- `confirmClosingDocument: false`
- `renameUntitledFileOnSave: false`
- `maxNumberRecents: 0`

**Output path:** `frontend/public/jupyterlite/`

**Git note:** `frontend/public/jupyterlite/` remains generated artefact output and is ignored by `.gitignore`.

### 3.2 Bridge Extension

**Directory:** `jupyterlite-bridge/`

- Plugin type: `JupyterFrontEndPlugin<void>` with `autoStart: true`.
- Build command: `npm run build`.
- Packaged as a proper labextension (`jupyter labextension build .`) into `labextension/`.

**Bridge commands:**

| Command                     | Direction        | Purpose                                               |
| --------------------------- | ---------------- | ----------------------------------------------------- |
| `ping`                    | Parent -> iframe | Health check for bridge readiness.                    |
| `ready`                   | Iframe -> parent | Bridge ready signal (sent multiple times on startup). |
| `load-notebook`           | Parent -> iframe | Save/open notebook payload and inject `workspace_files` inside JupyterLite. |
| `get-notebook-state`      | Parent -> iframe | Return full current notebook JSON.                    |
| `get-current-cell`        | Parent -> iframe | Return active cell source and index.                  |
| `get-error-output`        | Parent -> iframe | Return latest error traceback text if present.        |
| `notebook-dirty`          | Iframe -> parent | Notify that notebook content changed.                 |
| `notebook-save-requested` | Iframe -> parent | Notify that user triggered manual save in Jupyter UI. |

### 3.3 Kernel and Package Defaults

JupyterLite config is patched to use:

- Kernel display name: `Numerical Computing`
- Pyodide packages preloaded:
  - `numpy`
  - `scipy`
  - `pandas`
  - `matplotlib`
  - `sympy`

### 3.4 Single-Notebook Workspace Isolation

The bridge enforces single-document behaviour:

- Forces JupyterLab shell mode to `single-document`.
- Hides sidebars and status bar in workspace mode.
- Best-effort saves the active notebook before switching workspaces.
- Disposes unrelated main-area widgets without triggering close-confirm prompts.
- Deletes notebook files other than the active workspace notebook.
- Shuts down unrelated sessions.
- Clears recent documents (`docmanager:clear-recents`).
- Generates a title-based filename so JupyterLab naturally shows the title in the tab. Sets `document.title` and `panel.title.caption` but does not override `panel.title.label` (to avoid desynchronising internal path tracking).
- Overrides `docmanager:download` so the downloaded file uses the display title as its filename.

This is the main protection against notebook cross-visibility and stale state carry-over.

---

## 4. Backend Implementation

### 4.1 Migrations and Data Model

#### Migration `004_add_user_notebooks_table.py`

Adds `user_notebooks` for personal notebooks:

- ownership (`user_id`)
- metadata (`title`, `original_filename`, `size_bytes`)
- storage info (`stored_filename`, `storage_path`)
- current state (`notebook_json`)
- extracted context (`extracted_text`)

#### Migration `005_add_admin_and_zones.py`

Adds:

- `users.is_admin`
- `learning_zones`
- `zone_notebooks`
- `zone_shared_files`
- `zone_notebook_progress` with unique `(user_id, zone_notebook_id)`

`learning_zones.description` and `zone_notebooks.description` are nullable, so zone and notebook descriptions are optional.

#### Migration `006_add_scoped_chat_session_uniqueness.py`

Adds partial unique index on `chat_sessions`:

- unique on `(user_id, session_type, module_id)`
- applied only when `session_type IN ('notebook', 'zone')` and `module_id IS NOT NULL`

This prevents duplicate scoped sessions for the same user and notebook scope.

### 4.2 Notebook Storage Layout

Root storage comes from `NOTEBOOK_STORAGE_DIR` (default `/tmp/ai_coding_tutor_notebooks`).

- Personal notebooks:
  - `/tmp/ai_coding_tutor_notebooks/<normalised_user_email>/`
- Admin zone content:
  - `/tmp/ai_coding_tutor_notebooks/learning_zone_notebooks/<zone_id>/notebooks`
  - `/tmp/ai_coding_tutor_notebooks/learning_zone_notebooks/<zone_id>/shared`

Shared zone files keep their relative paths and are served to zone notebook runtime as `workspace_files`. The server stores notebook payloads independently in backend-managed files and DB JSON fields. Workspace edits update backend state, not the original local upload file on the user's machine.

### 4.3 Personal Notebook Service and API

**Service file:** `backend/app/services/notebook_service.py`

Core service behaviours:

- Validate `.ipynb` extension and JSON structure.
- Enforce notebook count and file size limits from config.
- Persist notebook file and JSON state.
- Refresh extracted text on demand for tutor context.
- Rename notebook title with normalised display filename.

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
| `/api/zones/{zone_id}`                                  | GET    | Zone detail + notebook list +`has_progress`.    |
| `/api/zones/{zone_id}/notebooks/{notebook_id}`          | GET    | Return notebook JSON (progress copy or original). |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/runtime-files` | GET    | Return runtime dependency files for zone notebook execution. |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/progress` | PUT    | Save user's progress notebook state.              |
| `/api/zones/{zone_id}/notebooks/{notebook_id}/progress` | DELETE | Reset user's progress to original.                |

**Admin router:** `backend/app/routers/admin.py`

All endpoints require `get_admin_user`. All mutation endpoints log actions to `admin_audit_log`.

| Endpoint                                         | Method | Behaviour                                 |
| ------------------------------------------------ | ------ | ----------------------------------------- |
| `/api/admin/zones`                             | GET    | List zones with notebook counts.          |
| `/api/admin/zones`                             | POST   | Create zone.                              |
| `/api/admin/zones/{zone_id}`                   | PUT    | Update zone fields.                       |
| `/api/admin/zones/{zone_id}`                   | DELETE | Delete zone and related data.             |
| `/api/admin/zones/{zone_id}/notebooks`         | GET    | List notebooks in zone.                   |
| `/api/admin/zones/{zone_id}/notebooks`         | POST   | Upload notebook to zone.                  |
| `/api/admin/zones/{zone_id}/assets`            | POST   | Import files/folders into a zone; `.ipynb` files auto-create notebooks and other files become shared zone files. |
| `/api/admin/zones/{zone_id}/shared-files`      | GET    | List shared zone files for admin management. |
| `/api/admin/notebooks/{notebook_id}/metadata`  | PATCH  | Update zone notebook title and optional description. |
| `/api/admin/notebooks/{notebook_id}`           | PUT    | Replace notebook content.                 |
| `/api/admin/shared-files/{shared_file_id}`     | DELETE | Delete shared zone file.                  |
| `/api/admin/notebooks/{notebook_id}`           | DELETE | Delete zone notebook.                     |
| `/api/admin/zones/{zone_id}/notebooks/reorder` | PUT    | Reorder notebooks.                        |
| `/api/admin/audit-log`                         | GET    | Return paginated admin audit log entries. |

Zone and notebook name updates are recorded in `admin_audit_log` with change details.

### 4.5 Notebook-Aware and Scoped Chat

**Schema update:** `backend/app/schemas/chat.py`

`ChatMessageIn` supports:

- `notebook_id`
- `zone_notebook_id`
- `cell_code`
- `error_output`

**Router logic:** `backend/app/routers/chat.py`

- Accepts only one notebook scope per message (`notebook_id` or `zone_notebook_id`).
- Builds notebook context block and appends it to `build_system_prompt(...)`.
- Uses scoped `session_type`:
  - `general`
  - `notebook`
  - `zone`
- Reuses a provided `session_id` only when it matches the current scope; mismatched IDs are ignored and the current scope is resolved instead.
- Keeps general sidebar clean by returning only `general` sessions from `/api/chat/sessions`.
- Adds `/api/chat/sessions/find` for scoped session restore in workspace.

**Service logic:** `backend/app/services/chat_service.py`

- `get_or_create_session(...)` resolves and reuses scoped sessions, and validates that any provided `session_id` matches the active request scope before reuse.
- Handles unique-index races with `IntegrityError` fallback lookup.

### 4.6 Admin Email Rules

**Config:** `backend/app/config.py`

`ADMIN_EMAIL` supports:

- comma-separated values
- space-separated values
- semicolon-separated values
- JSON array strings

Examples:

- `ADMIN_EMAIL=alice@example.com,bob@example.com`
- `ADMIN_EMAIL=alice@example.com bob@example.com`
- `ADMIN_EMAIL=["alice@example.com","bob@example.com"]`

**Promotion flow:**

- On registration (`auth.py`): matching email gets `is_admin=True`.
- On startup (`init_db.py`): existing matching users are promoted.

---

## 5. Frontend Implementation

### 5.1 Routes and Navigation

**App routes:** `frontend/src/App.tsx`

- `/my-notebooks`
- `/notebook/:notebookId`
- `/learning-hub`
- `/zones/:zoneId`
- `/zone-notebook/:zoneId/:notebookId`
- `/admin`
- `/health`

**Navbar:** `frontend/src/components/Navbar.tsx`

- Shows `Chat`, `My Notebooks`, `Learning Hub`, `Profile` for logged-in users.
- Shows `Admin` only when `user.is_admin` is true.

### 5.2 My Notebooks Page

**File:** `frontend/src/notebook/MyNotebooksPage.tsx`

Implemented user actions:

- Upload `.ipynb`
- Open notebook workspace
- Rename notebook
- Delete notebook

Notebook cards show title, filename, size, and upload date.

### 5.3 Notebook Workspace Panel

**File:** `frontend/src/workspace/NotebookPanel.tsx`

Key behaviours:

- Loads `/jupyterlite/lab/index.html` in iframe with a cache-busting bridge version parameter.
- Waits for bridge readiness via `ping` polling (`waitForNotebookBridgeReady`).
- Loads notebook JSON from backend and sends `load-notebook`.
- In zone workspace mode, fetches `/api/zones/{zone_id}/notebooks/{notebook_id}/runtime-files` and passes them as `workspace_files` to `load-notebook`.
- Applies retry on load timeout for better stability.
- Bridge performs local in-browser save with a 5s debounce after edits.
- Listens for `notebook-dirty` and syncs to backend every 30s only when dirty.
- Syncs to backend immediately when user clicks Save in Jupyter UI.
- Sends one final `keepalive` save on `beforeunload` and `pagehide`.
- Reports save status: `Saved`, `Saving...`, `Unsaved changes`, `Save failed`.

### 5.4 Workspace Chat Panel

**File:** `frontend/src/workspace/WorkspaceChatPanel.tsx`

Key behaviours:

- Resolves scoped session via `/api/chat/sessions/find`.
- Restores scoped message history when available.
- Clears local chat state and temporarily disables input while scoped session restore is in progress.
- Sends messages with notebook scope and live cell/error context.
- Provides `New chat` button that deletes current scoped session and starts fresh.
- Workspace pages key the chat panel by scope so route changes remount the panel and close the previous WebSocket connection.

### 5.5 Zone Notebook Workspace

**File:** `frontend/src/workspace/ZoneNotebookWorkspacePage.tsx`

Differences from personal workspace:

- Uses zone notebook endpoints for load/save.
- Sends `zone_notebook_id` in chat scope.
- Loads zone runtime dependency files into notebook workspace before execution.
- Shows notebooks only in student UI; shared dependency file management is admin-only.
- Shows `Reset to Original` button in the top-right of notebook panel.
- Reset deletes progress and reloads notebook state.

### 5.6 Admin Dashboard

**File:** `frontend/src/admin/AdminDashboardPage.tsx`

Key behaviours:

- Creates and edits zones with optional descriptions.
- Imports files or folders into a zone via `/api/admin/zones/{zone_id}/assets`.
- Creates notebooks from imported `.ipynb` files.
- Lists and deletes shared zone dependency files via admin-only controls.
- Edits notebook metadata (title and optional description).
- Supports notebook replace, delete, and reorder actions.
- Shows usage and audit panels for admins.
- Provides a direct link to the frontend `/health` page for current model diagnostics and smoke-tested model availability.
- The `/health` page fetches model status data from `/api/health/ai/models`.

### 5.7 Split Layout Dependency

The project uses the official `react-split` package directly:

- import: `import Split from "react-split";`
- used in personal and zone workspace pages.

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
- [ ] Click `New chat` in workspace chat: scoped history resets for that notebook only.
- [ ] Switch between two notebook routes and send a message immediately after the page loads: the message is stored in the active notebook's scoped chat session only.
- [ ] Click `Reset to Original` in zone workspace: user progress is removed and original content reloads.

---

## 7. Known Constraints

- JupyterLite runs in browser WebAssembly, so performance is slower than native Python.
- Browser memory limits apply to large notebook workloads.
- Python packages are limited to what Pyodide can load.
- The notebook runtime is client-side; backend persists state but does not execute notebook code.
