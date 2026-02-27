# Semantic Recognition Testing

This document records calibration testing for the optional embedding-based semantic filters used by the chat pipeline:

- greeting detection (optional, disabled by default)
- off-topic filtering (optional, disabled by default)

The runtime default embedding provider is **Cohere `embed-v4.0`**. The application also supports **Vertex AI `multimodalembedding@001`** and **Voyage AI `voyage-multimodal-3.5`**.

## Current Runtime Scope

The embedding service is used only for the optional greeting/off-topic filters.

Same-problem detection, elaboration detection, and difficulty classification are handled by the LLM metadata routes (`Single-Pass Header Route` and `Two-Step Recovery Route`). Hint levels are computed deterministically by the backend using the gap formula (see `docs/pedagogy-algorithm.md`).

## Calibration Script

The calibration script is `backend/tests/test_semantic_thresholds.py`.

It imports anchors and the current threshold profiles from `backend/app/ai/embedding_service.py`, embeds the calibration corpus once per provider, and then runs repeated local threshold sweeps to select provider-specific thresholds. Repeated evaluation logic is implemented with shared helper functions to avoid duplication.

The script uses the configured provider model IDs and Google Vertex locations from environment variables. In the repository env examples, the Vertex Gemini and Vertex embedding locations are set to **London (`europe-west2`)**.

Run it manually from `backend/`:

```bash
PYTHONPATH=. python -m tests.test_semantic_thresholds
```

## Calibration Corpus

The script evaluates the same text-only corpus for each provider:

- greeting messages
- greeting false positives (for example, `"hello world"` programming prompts)
- greetings that also contain a real tutoring question
- on-topic coding/STEM prompts
- clearly off-topic prompts
- borderline/general prompts

This keeps the provider comparison consistent.

## Thresholds Used in the App (Current)

Provider order is kept consistent across code and documentation:

1. Cohere
2. Vertex AI
3. Voyage AI

### Cohere (`embed-v4.0`)

| Check | Current rule |
| --- | --- |
| Greeting detection | `greeting_score >= 0.990` |
| Off-topic filtering (relative rule) | `off_topic_score >= 0.650` and `(off_topic_score - topic_score) >= 0.386` |
| Off-topic fallback (topic-only backup) | `topic_score < 0.361` |

### Vertex AI (`multimodalembedding@001`)

| Check | Current rule |
| --- | --- |
| Greeting detection | `greeting_score >= 0.935` |
| Off-topic filtering (relative rule) | `off_topic_score >= 0.808` and `(off_topic_score - topic_score) >= 0.070` |
| Off-topic fallback (topic-only backup) | `topic_score < 0.751` |

### Voyage AI (`voyage-multimodal-3.5`)

| Check | Current rule |
| --- | --- |
| Greeting detection | `greeting_score >= 0.970` |
| Off-topic filtering (relative rule) | `off_topic_score >= 0.570` and `(off_topic_score - topic_score) >= 0.442` |
| Off-topic fallback (topic-only backup) | `topic_score < 0.294` |

These values match `EMBEDDING_THRESHOLDS` in `backend/app/ai/embedding_service.py`.

## Calibration Results (Latest Run)

The threshold search is precision-biased:

- minimise false positives first
- then maximise true positives
- then prefer stricter thresholds when tied

### Greeting Detection Summary

| Provider | Greeting true scores (min / max / avg) | Greeting negatives (min / max / avg) | Selected threshold | Result |
| --- | --- | --- | ---: | --- |
| Cohere | `0.463 / 1.000 / 0.940` | `0.261 / 0.634 / 0.481` | `0.990` | `TP=8, FP=0, FN=1, TN=7` |
| Vertex AI | `0.939 / 1.000 / 0.993` | `0.735 / 0.872 / 0.803` | `0.935` | `TP=9, FP=0, FN=0, TN=7` |
| Voyage AI | `0.972 / 1.000 / 0.996` | `0.297 / 0.681 / 0.523` | `0.970` | `TP=9, FP=0, FN=0, TN=7` |

### Off-Topic Filtering Summary (Relative Rule)

| Provider | Selected `off_topic_score` min | Selected margin min | Result |
| --- | ---: | ---: | --- |
| Cohere | `0.650` | `0.386` | `TP=5, FP=0, FN=0, TN=10` |
| Vertex AI | `0.808` | `0.070` | `TP=5, FP=0, FN=0, TN=10` |
| Voyage AI | `0.570` | `0.442` | `TP=5, FP=0, FN=0, TN=10` |

### Off-Topic Fallback Summary (Topic-Only Backup)

| Provider | Selected `topic_score` max | Result |
| --- | ---: | --- |
| Cohere | `0.361` | `TP=4, FP=0, FN=1, TN=10` |
| Vertex AI | `0.751` | `TP=3, FP=0, FN=2, TN=10` |
| Voyage AI | `0.294` | `TP=5, FP=0, FN=0, TN=10` |

The relative rule is the primary path for all three provider profiles. The topic-only threshold is kept in each profile as a backup.

## Anchor Sets

The embedding service pre-embeds three anchor groups during initialisation:

- `GREETING_ANCHORS`
- `TOPIC_ANCHORS`
- `OFF_TOPIC_ANCHORS`

The topic anchors intentionally use specific coding/STEM phrases (rather than mostly single words) to reduce false matches on short conversational text.

## Operational Notes

- These filters are **disabled by default**.
- If embedding credentials are unavailable, the default chat path still works.
- When the filters are enabled but the embedding service is unavailable, the backend logs a warning and proceeds without filtering (`fail-open`).

## Limitations

- Thresholds are provider-specific and corpus-specific. They should be rechecked after model/provider changes.
- This calibration corpus is intentionally compact for repeatable local testing. Production traffic can still surface new edge cases.
