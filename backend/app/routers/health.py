"""Health check endpoints and browser-facing model diagnostics page."""

from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter

from app.ai.verify_keys import smoke_test_supported_models, verify_all_keys
from app.config import settings

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


def _current_model_snapshot() -> dict:
    llm_models = {
        "google": settings.llm_model_google,
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
    }
    embedding_models = {
        "cohere": settings.embedding_model_cohere,
        "vertex": settings.embedding_model_vertex,
        "voyage": settings.embedding_model_voyage,
    }
    active_llm = {
        "provider": settings.llm_provider,
        "model": llm_models.get(settings.llm_provider, ""),
    }
    if settings.llm_provider == "google":
        active_llm["google_gemini_transport"] = settings.google_gemini_transport
    active_embedding = {
        "provider": settings.embedding_provider,
        "model": embedding_models.get(settings.embedding_provider, ""),
    }
    return {
        "llm_provider": settings.llm_provider,
        "google_gemini_transport": settings.google_gemini_transport,
        "llm_models": llm_models,
        "active_llm": active_llm,
        "embedding_provider": settings.embedding_provider,
        "embedding_models": embedding_models,
        "active_embedding": active_embedding,
    }


async def ai_model_catalog_health_check(force: bool = False) -> dict:
    """Return configured model selections and smoke-tested available models."""
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
        google_transport=settings.google_gemini_transport,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_location=settings.google_vertex_gemini_location,
        cohere_key=settings.cohere_api_key,
        voyage_key=settings.voyageai_api_key,
        vertex_embedding_location=settings.google_vertex_embedding_location,
    )
    payload = {
        "current": _current_model_snapshot(),
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
        configured = bool(details.get("configured"))
        reason = str(details.get("reason", "") or "")
        provider_label = provider
        if provider == "google" and details.get("transport"):
            provider_label = f"google ({details['transport']})"
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
        status_html = "Configured" if configured else "Not configured"
        if reason:
            status_html += f"<br><span class='muted'>{escape(reason)}</span>"
        rows.append(
            "<tr>"
            f"<td>{escape(provider_label)}</td>"
            f"<td>{status_html}</td>"
            f"<td>{checked_html}</td>"
            f"<td>{available_html}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_health_page_html(data: dict) -> str:
    """Render a simple browser-facing `/health` page without changing probe semantics."""
    current = data.get("current", {})
    smoke = data.get("smoke_tested_models", {})
    checked_at = escape(str(data.get("checked_at", "")))
    cached = "Yes" if data.get("cached") else "No"

    active_llm = current.get("active_llm", {})
    active_embedding = current.get("active_embedding", {})
    llm_models = current.get("llm_models", {})
    embedding_models = current.get("embedding_models", {})

    llm_config_rows = "".join(
        "<tr>"
        f"<td>{escape(provider)}</td>"
        f"<td><code>{escape(str(model_id))}</code></td>"
        "</tr>"
        for provider, model_id in llm_models.items()
    )
    embedding_config_rows = "".join(
        "<tr>"
        f"<td>{escape(provider)}</td>"
        f"<td><code>{escape(str(model_id))}</code></td>"
        "</tr>"
        for provider, model_id in embedding_models.items()
    )

    google_transport = current.get("google_gemini_transport", "")
    active_llm_transport_note = (
        f" ({escape(str(google_transport))})"
        if active_llm.get("provider") == "google" and google_transport
        else ""
    )

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
      --ok: #0f766e;
      --bad: #b91c1c;
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
    .grid.two {{ grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }}
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
    .actions {{ margin-top: .75rem; }}
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
    .banner {{
      border-left: 4px solid var(--brand);
      background: #f7fbff;
      padding: .75rem .9rem;
      margin-bottom: 1rem;
      border-radius: 10px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>System Health</h1>
    <p>Browser view for the current configured models and smoke-tested available models.</p>
    <div class="meta">
      <div class="pill"><strong>Checked at</strong> {checked_at}</div>
      <div class="pill"><strong>Cached</strong> {cached}</div>
    </div>
    <div class="actions">
      <a class="button" href="/health?force=true">Run smoke checks again</a>
    </div>

    <div class="banner">
      <p>
        <strong>Current LLM:</strong>
        <code>{escape(str(active_llm.get("provider", "")))}</code>
        <code>{escape(str(active_llm.get("model", "")))}</code>{active_llm_transport_note}
        &nbsp;|&nbsp;
        <strong>Current embeddings:</strong>
        <code>{escape(str(active_embedding.get("provider", "")))}</code>
        <code>{escape(str(active_embedding.get("model", "")))}</code>
      </p>
    </div>

    <div class="grid two">
      <section class="card">
        <h2>Configured LLM Models</h2>
        <table>
          <thead><tr><th>Provider</th><th>Configured model</th></tr></thead>
          <tbody>{llm_config_rows}</tbody>
        </table>
      </section>
      <section class="card">
        <h2>Configured Embedding Models</h2>
        <table>
          <thead><tr><th>Provider</th><th>Configured model</th></tr></thead>
          <tbody>{embedding_config_rows}</tbody>
        </table>
      </section>
    </div>

    <div class="grid" style="margin-top: 1rem;">
      <section class="card">
        <h2>Smoke-Tested Available LLM Models</h2>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Provider status</th>
              <th>Checked models</th>
              <th>Available models</th>
            </tr>
          </thead>
          <tbody>{_render_model_status_table(smoke.get("llm", {}))}</tbody>
        </table>
      </section>
      <section class="card">
        <h2>Smoke-Tested Available Embedding Models</h2>
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Provider status</th>
              <th>Checked models</th>
              <th>Available models</th>
            </tr>
          </thead>
          <tbody>{_render_model_status_table(smoke.get("embeddings", {}))}</tbody>
        </table>
      </section>
    </div>
  </div>
</body>
</html>
"""


@router.get("/ai")
async def ai_health_check(force: bool = False):
    """Check that external AI service API keys are valid."""
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
        google_transport=settings.google_gemini_transport,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_model_id=settings.llm_model_google,
        google_location=settings.google_vertex_gemini_location,
        anthropic_model_id=settings.llm_model_anthropic,
        openai_model_id=settings.llm_model_openai,
        vertex_embedding_model_id=settings.embedding_model_vertex,
        vertex_embedding_location=settings.google_vertex_embedding_location,
        cohere_model_id=settings.embedding_model_cohere,
        cohere_key=settings.cohere_api_key,
        voyage_model_id=settings.embedding_model_voyage,
        voyage_key=settings.voyageai_api_key,
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
    """Return configured model selections and smoke-tested available models."""
    return await ai_model_catalog_health_check(force=force)
