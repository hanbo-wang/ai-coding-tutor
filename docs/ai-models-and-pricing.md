# AI Models and Pricing

This project uses a multi-provider AI layer with a low-cost default path:

- **LLM default:** Vertex AI Gemini `gemini-3-flash-preview`
- **Embedding default:** Vertex AI `multimodalembedding@001`
- **Google auth:** one Google Cloud service account JSON file (path in `.env`), with code-managed Bearer token refresh

The backend also supports Anthropic and OpenAI LLMs, plus Cohere and Voyage embeddings, as fallbacks or operator-selected providers.

## Why Vertex AI + Gemini 3 Flash (Default)

- **Low cost:** Gemini 3 Flash preview pricing is materially lower than the higher-capability models for routine tutoring turns.
- **Good latency/performance balance:** it is fast enough for streaming chat and strong enough for tutoring workflows when paired with the pedagogy engine and context controls.
- **Simple operations:** the same Google Cloud service account is used for both Gemini and Vertex multimodal embeddings, so there is one auth path to manage.
- **Clean failover story:** Anthropic and OpenAI remain available without changing the app architecture.

## Supported LLM Models

| Provider | Model (API ID) | Authentication | Notes |
| --- | --- | --- | --- |
| Google Vertex AI | `gemini-3-flash-preview` | Google service account -> Bearer token | Default LLM |
| Google Vertex AI | `gemini-3.1-pro-preview` | Google service account -> Bearer token | Higher-cost, higher-capability option |
| Anthropic | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | Strong general reasoning |
| Anthropic | `claude-haiku-4-5` | `ANTHROPIC_API_KEY` | Lower-cost Anthropic option |
| OpenAI | `gpt-5.2` | `OPENAI_API_KEY` | Higher-capability OpenAI option |
| OpenAI | `gpt-5-mini` | `OPENAI_API_KEY` | Lower-cost OpenAI option |

## Supported Embedding Models

| Provider | Model (API ID) | Authentication | Notes |
| --- | --- | --- | --- |
| Google Vertex AI | `multimodalembedding@001` | Google service account -> Bearer token | Default embedding provider; text + image |
| Cohere | `embed-v4.0` | `COHERE_API_KEY` | Supported fallback |
| Voyage AI | `voyage-multimodal-3.5` | `VOYAGEAI_API_KEY` | Supported fallback |

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

### Embedding Pricing (USD)

| Provider | Model | Unit | Price |
| --- | --- | --- | ---: |
| Google Vertex AI | `multimodalembedding@001` | Text input (per 1,000 chars) | \$0.0002 |
| Google Vertex AI | `multimodalembedding@001` | Image input (per image) | \$0.0001 |
| Cohere | `embed-v4.0` (Embed 4) | Text / document tokens (per 1M tokens) | \$0.12 |
| Cohere | `embed-v4.0` (Embed 4) | Image tokens (per 1M tokens) | \$0.47 |
| Voyage AI | `voyage-multimodal-3.5` | Text tokens (per 1M tokens) | \$0.02 |
| Voyage AI | `voyage-multimodal-3.5` | Image input (per image) | \$0.04 |

## Notes

- Pricing can change, especially for preview models. Check the official provider pricing pages before relying on these figures for budgeting.
- Admin cost totals in the dashboard use stored per-message `estimated_cost_usd`. Older messages created before model-cost tracking may not have a stored cost value, and coverage is reported separately.

