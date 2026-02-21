#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -d "$PROJECT_ROOT/.tools/node-v24.13.0-linux-x64/bin" ]; then
  export PATH="$PROJECT_ROOT/.tools/node-v24.13.0-linux-x64/bin:$PATH"
fi
if [ -d "$HOME/.local/node-v24.13.0-linux-x64/bin" ]; then
  export PATH="$HOME/.local/node-v24.13.0-linux-x64/bin:$PATH"
fi
export PATH="$HOME/.local/bin:$PATH"

python3 -m pip install --user --break-system-packages jupyterlite-core jupyterlite-pyodide-kernel jupyterlab

cd "$PROJECT_ROOT/jupyterlite-bridge"
npm install
npm run build
cd "$PROJECT_ROOT"

# Build in Linux tmpfs first to avoid heavy I/O stalls on /mnt/* mounts.
TMP_ROOT="$(mktemp -d)"
TMP_LITE_DIR="$TMP_ROOT/jupyterlite-project"
TMP_EXT_DIR="$TMP_ROOT/jupyterlite-bridge"
TMP_LITE_OUT="$TMP_ROOT/jupyterlite-out"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_LITE_DIR" "$TMP_EXT_DIR" "$TMP_LITE_OUT"
rsync -a --delete "$PROJECT_ROOT/jupyterlite-bridge/labextension/" "$TMP_EXT_DIR/"

cat > "$TMP_LITE_DIR/jupyter-lite.json" <<'JSON'
{
  "jupyter-config-data": {
    "exposeAppInBrowser": true,
    "defaultKernelName": "Numerical Computing",
    "disabledExtensions": [
      "@jupyterlab/statusbar-extension",
      "@jupyterlab/mainmenu-extension:recents"
    ],
    "litePluginSettings": {
      "@jupyterlab/docmanager-extension:plugin": {
        "autosave": true,
        "autosaveInterval": 12,
        "confirmClosingDocument": false,
        "renameUntitledFileOnSave": false,
        "maxNumberRecents": 0
      },
      "@jupyterlite/pyodide-kernel-extension:kernel": {
        "loadPyodideOptions": {
          "packages": [
            "numpy",
            "scipy",
            "pandas",
            "matplotlib",
            "sympy"
          ]
        }
      }
    }
  }
}
JSON

BUILD_ARGS=(
  jupyter lite build
  --LiteBuildConfig.lite_dir="$TMP_LITE_DIR"
  --output-dir "$TMP_LITE_OUT"
  --LiteBuildConfig.federated_extensions="$TMP_EXT_DIR"/
)

# pip --user installs lab extensions under ~/.local/share/jupyter/labextensions.
USER_LABEXTENSIONS="$HOME/.local/share/jupyter/labextensions"
if [ -d "$USER_LABEXTENSIONS" ]; then
  BUILD_ARGS+=(--FederatedExtensionAddon.extra_labextensions_path="$USER_LABEXTENSIONS")
fi

"${BUILD_ARGS[@]}"

mkdir -p frontend/public/jupyterlite
rsync -a --delete "$TMP_LITE_OUT"/ frontend/public/jupyterlite/

python3 - <<'PY'
import json
from pathlib import Path

KERNEL_NAME = "Numerical Computing"
PACKAGES = ["numpy", "scipy", "pandas", "matplotlib", "sympy"]
BRIDGE_EXTENSION_NAME = "jupyterlite-bridge"
DISABLED_EXTENSIONS = [
    "@jupyterlab/statusbar-extension",
    "@jupyterlab/mainmenu-extension:recents",
]
DOCMANAGER_PLUGIN_ID = "@jupyterlab/docmanager-extension:plugin"
DOCMANAGER_AUTOSAVE_INTERVAL_SECONDS = 12

root = Path("frontend/public/jupyterlite")
root_config_path = root / "jupyter-lite.json"

def ensure_disabled_extensions(config: dict) -> None:
    disabled = config.get("disabledExtensions")
    if isinstance(disabled, dict):
        for extension in DISABLED_EXTENSIONS:
            disabled[extension] = True
        return
    if isinstance(disabled, list):
        for extension in DISABLED_EXTENSIONS:
            if extension not in disabled:
                disabled.append(extension)
        return
    config["disabledExtensions"] = DISABLED_EXTENSIONS.copy()

def ensure_docmanager_settings(config: dict) -> None:
    plugin_settings = config.setdefault("litePluginSettings", {})
    docmanager_settings = plugin_settings.setdefault(DOCMANAGER_PLUGIN_ID, {})
    docmanager_settings["autosave"] = True
    docmanager_settings["autosaveInterval"] = DOCMANAGER_AUTOSAVE_INTERVAL_SECONDS
    docmanager_settings["confirmClosingDocument"] = False
    docmanager_settings["renameUntitledFileOnSave"] = False
    docmanager_settings["maxNumberRecents"] = 0

for target in [
    root_config_path,
    root / "lab" / "jupyter-lite.json",
    root / "notebooks" / "jupyter-lite.json",
    root / "tree" / "jupyter-lite.json",
    root / "repl" / "jupyter-lite.json",
    root / "edit" / "jupyter-lite.json",
    root / "consoles" / "jupyter-lite.json",
]:
    if not target.exists():
        continue

    payload = json.loads(target.read_text(encoding="utf-8"))
    config = payload.setdefault("jupyter-config-data", {})
    config["exposeAppInBrowser"] = True
    ensure_disabled_extensions(config)
    ensure_docmanager_settings(config)

    if target == root_config_path:
        config["defaultKernelName"] = KERNEL_NAME
        plugin_settings = config.setdefault("litePluginSettings", {})
        kernel_settings = plugin_settings.setdefault(
            "@jupyterlite/pyodide-kernel-extension:kernel", {}
        )
        load_options = kernel_settings.setdefault("loadPyodideOptions", {})
        load_options["packages"] = PACKAGES

    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

root_payload = json.loads(root_config_path.read_text(encoding="utf-8"))
root_config = root_payload.get("jupyter-config-data", {})
federated_extensions = root_config.get("federated_extensions", [])
bridge_exists = (
    isinstance(federated_extensions, list)
    and any(
        isinstance(extension, dict)
        and extension.get("name") == BRIDGE_EXTENSION_NAME
        for extension in federated_extensions
    )
)
if not bridge_exists:
    raise RuntimeError(
        "jupyterlite-bridge extension was not registered in jupyter-lite.json"
    )

static_dir = root / "extensions" / "@jupyterlite" / "pyodide-kernel-extension" / "static"
needle = 'name:"python",display_name:"Python (Pyodide)"'
replacement = f'name:"{KERNEL_NAME}",display_name:"{KERNEL_NAME}"'

if static_dir.exists():
    for js_file in static_dir.glob("*.js"):
        content = js_file.read_text(encoding="utf-8")
        if needle not in content:
            continue
        js_file.write_text(content.replace(needle, replacement, 1), encoding="utf-8")
        break
PY
