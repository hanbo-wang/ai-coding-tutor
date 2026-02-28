"""Health check endpoints and browser-facing model diagnostics page."""

from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter

from app.ai.verify_keys import smoke_test_supported_models, verify_all_keys
from app.config import settings
from app.ai.model_registry import normalise_llm_provider

router = APIRouter(prefix="/api/health", tags=["health"])
AI_HEALTH_CACHE_TTL = timedelta(seconds=30)
_last_ai_health_result: dict[str, bool] | None = None
_last_ai_health_at: datetime | None = None
AI_MODEL_HEALTH_CACHE_TTL = timedelta(seconds=60)
_last_ai_models_result: dict | None = None
_last_ai_models_at: datetime | None = None


def _utc_now_naive() -> datetime:
    """Return a naive UTC datetime without deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def invalidate_ai_model_catalog_cache() -> None:
    """Clear cached `/api/health/ai/models` data after runtime model changes."""
    global _last_ai_models_result, _last_ai_models_at
    _last_ai_models_result = None
    _last_ai_models_at = None


def _active_google_provider() -> str:
    transport = str(settings.google_gemini_transport).strip().lower()
    return "google-aistudio" if transport == "aistudio" else "google-vertex"


def _current_runtime_llm() -> dict[str, str | None]:
    provider = normalise_llm_provider(settings.llm_provider)
    if provider == "google":
        active_provider = _active_google_provider()
    else:
        active_provider = provider
    model_by_provider = {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        "google": settings.llm_model_google,
    }
    return {
        "provider": active_provider,
        "model": model_by_provider.get(provider, ""),
        "google_gemini_transport": settings.google_gemini_transport if provider == "google" else None,
    }


async def ai_model_catalog_health_check(force: bool = False) -> dict:
    """Return smoke-tested available LLM models only."""
    global _last_ai_models_result, _last_ai_models_at

    now = _utc_now_naive()
    if (
        not force
        and _last_ai_models_result is not None
        and _last_ai_models_at is not None
        and (now - _last_ai_models_at) <= AI_MODEL_HEALTH_CACHE_TTL
    ):
        return {
            **_last_ai_models_result,
            "cached": True,
            "checked_at": _last_ai_models_at.isoformat() + "Z",
        }

    smoke_results = await smoke_test_supported_models(
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_location=settings.google_vertex_gemini_location,
    )
    payload = {
        "current": _current_runtime_llm(),
        "smoke_tested_models": smoke_results,
    }
    _last_ai_models_result = payload
    _last_ai_models_at = now
    return {
        **payload,
        "cached": False,
        "checked_at": now.isoformat() + "Z",
    }


def _render_model_status_table(group: dict[str, dict]) -> str:
    rows: list[str] = []
    for provider, details in group.items():
        checked_models = details.get("checked_models", {})
        available_models = details.get("available_models", [])
        ready = bool(details.get("ready"))
        reason = str(details.get("reason", "") or "")
        transport = str(details.get("transport", "") or "")

        checked_html = (
            "<ul>"
            + "".join(
                f"<li><code>{escape(model_id)}</code>: {'OK' if ok else 'FAILED'}</li>"
                for model_id, ok in checked_models.items()
            )
            + "</ul>"
            if checked_models
            else "<span class='muted'>No smoke checks run</span>"
        )
        available_html = (
            ", ".join(f"<code>{escape(model_id)}</code>" for model_id in available_models)
            if available_models
            else "<span class='muted'>None</span>"
        )
        status_html = "Ready" if ready else "Unavailable"
        if reason:
            status_html += f"<br><span class='muted'>{escape(reason)}</span>"

        display_provider = provider
        if transport:
            display_provider = f"{provider} ({transport})"

        rows.append(
            "<tr>"
            f"<td>{escape(display_provider)}</td>"
            f"<td>{status_html}</td>"
            f"<td>{checked_html}</td>"
            f"<td>{available_html}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_health_page_html(data: dict) -> str:
    """Render a simple browser-facing `/health` page without changing probe semantics."""
    smoke = data.get("smoke_tested_models", {})
    current = data.get("current", {})
    current_provider = escape(str(current.get("provider", "")))
    current_model = escape(str(current.get("model", "")))
    checked_at = escape(str(data.get("checked_at", "")))
    cached = "Yes" if data.get("cached") else "No"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Health | AI Coding Tutor</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4f7fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #475569;
      --line: #dbe2ea;
      --brand: #0b3a67;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #edf3fa 0%, var(--bg) 48%, #eef5fb 100%);
      color: var(--ink);
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 2rem 1rem 3rem; }}
    h1 {{ margin: 0 0 .5rem; font-size: 2rem; color: var(--brand); }}
    h2 {{ margin: 0 0 .75rem; font-size: 1.1rem; color: var(--brand); }}
    p {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .grid {{ display: grid; gap: 1rem; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 1rem;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    .meta {{ margin-bottom: 1rem; display: flex; flex-wrap: wrap; gap: .75rem 1rem; }}
    .pill {{
      display: inline-flex; align-items: center; gap: .4rem;
      border: 1px solid var(--line); border-radius: 999px; padding: .35rem .7rem;
      background: #fff; color: var(--muted); font-size: .9rem;
    }}
    .pill strong {{ color: var(--ink); }}
    .actions {{ margin-top: .75rem; margin-bottom: 1rem; }}
    .button {{
      display: inline-block; text-decoration: none; color: white; background: var(--brand);
      border-radius: 10px; padding: .55rem .85rem; font-weight: 600; font-size: .9rem;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      text-align: left; vertical-align: top; padding: .6rem .55rem;
      border-top: 1px solid var(--line); font-size: .92rem;
    }}
    th {{ color: var(--muted); font-weight: 600; background: #f8fbff; }}
    tr:first-child td, tr:first-child th {{ border-top: 0; }}
    code {{
      background: #eef4fb; border: 1px solid #d8e4f1; border-radius: 6px;
      padding: .1rem .35rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: .85em;
    }}
    ul {{ margin: 0; padding-left: 1rem; }}
    li {{ margin: .15rem 0; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>System Health</h1>
    <p>Current running model and smoke-tested LLM provider availability.</p>
    <div class="meta">
      <div class="pill"><strong>Current model</strong> <code>{current_provider} / {current_model}</code></div>
      <div class="pill"><strong>Checked at</strong> {checked_at}</div>
      <div class="pill"><strong>Cached</strong> {cached}</div>
    </div>
    <div class="actions">
      <a class="button" href="/health?force=true">Run smoke checks again</a>
    </div>

    <div class="grid">
      <section class="card">
        <h2>Smoke-Tested Available LLM Models</h2>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Checked models</th>
              <th>Available models</th>
            </tr>
          </thead>
          <tbody>{_render_model_status_table(smoke.get("llm", {}))}</tbody>
        </table>
      </section>
    </div>
  </div>
</body>
</html>
"""


@router.get("/ai")
async def ai_health_check(force: bool = False):
    """Check that external LLM service API keys are valid."""
    global _last_ai_health_result, _last_ai_health_at

    now = _utc_now_naive()
    if (
        not force
        and _last_ai_health_result is not None
        and _last_ai_health_at is not None
        and (now - _last_ai_health_at) <= AI_HEALTH_CACHE_TTL
    ):
        return {
            **_last_ai_health_result,
            "cached": True,
            "checked_at": _last_ai_health_at.isoformat() + "Z",
        }

    results = await verify_all_keys(
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_model_id=settings.llm_model_google,
        google_location=settings.google_vertex_gemini_location,
        anthropic_model_id=settings.llm_model_anthropic,
        openai_model_id=settings.llm_model_openai,
    )
    _last_ai_health_result = results
    _last_ai_health_at = now
    return {
        **results,
        "cached": False,
        "checked_at": now.isoformat() + "Z",
    }


@router.get("/ai/models")
async def ai_models_health_api(force: bool = False):
    """Return smoke-tested available LLM models."""
    return await ai_model_catalog_health_check(force=force)
