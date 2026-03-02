# AI Models and Pricing

This project uses a multi-provider AI layer with a low-cost default path:

- **LLM default:** Anthropic `claude-haiku-4-5`
- **Google transport and auth:** `GOOGLE_GEMINI_TRANSPORT` selects `aistudio` (`GOOGLE_API_KEY`) or `vertex` (Google Cloud service account JSON file, with code-managed Bearer token refresh)
- **Vertex location:** for current Gemini 3 preview models, use `GOOGLE_VERTEX_GEMINI_LOCATION=global`

The backend also supports Google Gemini and OpenAI LLMs as fallbacks or operator-selected providers.

## Why Claude Haiku 4.5 (Default)

- **Fast response speed:** Claude Haiku 4.5 provides low latency, making the streaming tutoring experience fluid.
- **Good reasoning quality:** strong enough for tutoring workflows when paired with the pedagogy engine and context controls.
- **Cost-effective:** a good balance of affordability and reasoning capability for high-frequency tutoring interactions.
- **Clean failover story:** Google Gemini and OpenAI remain available without changing the app architecture.

## Supported LLM Models

| Provider | Model (API ID) | Authentication | Notes |
| --- | --- | --- | --- |
| Google Gemini (AI Studio / Vertex AI) | `gemini-3-flash-preview` | `GOOGLE_GEMINI_TRANSPORT=aistudio` + `GOOGLE_API_KEY`, or `GOOGLE_GEMINI_TRANSPORT=vertex` + Google service account -> Bearer token | Both Google transports support text and image turns |
| Google Gemini (AI Studio / Vertex AI) | `gemini-3.1-pro-preview` | `GOOGLE_GEMINI_TRANSPORT=aistudio` + `GOOGLE_API_KEY`, or `GOOGLE_GEMINI_TRANSPORT=vertex` + Google service account -> Bearer token | Higher-cost, higher-capability option with the same transport support |
| Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | Strong general reasoning |
| Anthropic | `claude-haiku-4-5` | `ANTHROPIC_API_KEY` | Default LLM provider path |
| OpenAI | `gpt-5.2` | `OPENAI_API_KEY` | Higher-capability OpenAI option |
| OpenAI | `gpt-5-mini` | `OPENAI_API_KEY` | Lower-cost OpenAI option |

## Pricing Summary (Estimated Cost Metadata)

The application stores per-message provider/model metadata and estimated LLM cost. Figures below are used for estimates and visibility, not billing.

### LLM Pricing (USD, per 1M tokens)

| Provider | Model | Input | Output |
| --- | --- | ---: | ---: |
| Google Vertex AI | Gemini `gemini-3-flash-preview` | \$0.50 | \$3.00 |
| Google Vertex AI | Gemini `gemini-3.1-pro-preview` | \$2.00 | \$12.00 |
| Anthropic | Claude Sonnet `claude-sonnet-4-6` | \$3.00 | \$15.00 |
| Anthropic | Claude Haiku `claude-haiku-4-5` | \$1.00 | \$5.00 |
| OpenAI | `gpt-5.2` | \$1.25 | \$10.00 |
| OpenAI | `gpt-5-mini` | \$0.25 | \$2.00 |

## Notes

- Pricing can change, especially for preview models. Check the official provider pricing pages before relying on these figures for budgeting.
- Admin cost totals in the dashboard use stored per-message `estimated_cost_usd`. Older messages created before model-cost tracking may not have a stored cost value, and coverage is reported separately.
- The admin dashboard model switch panel shows the current running model, uses smoke-tested available models, defaults the model selector and selected-model usage panel to the running model, and shows per-model input/output pricing alongside overall usage totals.
