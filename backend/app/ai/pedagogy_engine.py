import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.ai.llm_base import LLMProvider
from app.ai.prompts import PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class StudentState:
    user_id: str
    effective_programming_level: float
    effective_maths_level: float
    current_programming_difficulty: int = 3
    current_maths_difficulty: int = 3
    current_programming_hint_level: int = 1
    current_maths_hint_level: int = 1
    starting_programming_hint_level: int = 1
    starting_maths_hint_level: int = 1
    last_question_text: Optional[str] = field(default=None, repr=False)
    last_answer_text: Optional[str] = field(default=None, repr=False)
    skip_next_ema_update_once: bool = False


@dataclass
class ProcessResult:
    programming_difficulty: Optional[int] = None
    maths_difficulty: Optional[int] = None
    programming_hint_level: Optional[int] = None
    maths_hint_level: Optional[int] = None
    is_same_problem: bool = False


@dataclass
class PedagogyFastSignals:
    has_previous_exchange: bool = False
    previous_question_text: Optional[str] = None
    previous_answer_text: Optional[str] = None


@dataclass
class StreamPedagogyMeta:
    same_problem: bool
    is_elaboration: bool
    programming_difficulty: int
    maths_difficulty: int
    programming_hint_level: int
    maths_hint_level: int
    source: str = "single_pass_header_route"


class PedagogyEngine:
    def __init__(
        self,
        llm: LLMProvider,
    ):
        self.llm = llm

    async def prepare_fast_signals(
        self,
        user_message: str,
        student_state: StudentState,
        username: str = "there",
        enable_greeting_filter: bool = False,
        enable_off_topic_filter: bool = False,
    ) -> PedagogyFastSignals:
        """Build fast non-LLM signals from local session context."""
        _ = user_message
        _ = username
        _ = enable_greeting_filter
        _ = enable_off_topic_filter

        previous_question = student_state.last_question_text or None
        previous_answer = student_state.last_answer_text or None
        has_previous_exchange = bool(
            (previous_question or "").strip() and (previous_answer or "").strip()
        )
        return PedagogyFastSignals(
            has_previous_exchange=has_previous_exchange,
            previous_question_text=previous_question,
            previous_answer_text=previous_answer,
        )

    @staticmethod
    def compute_hint_levels(
        *,
        programming_difficulty: int,
        maths_difficulty: int,
        student_state: StudentState,
        same_problem: bool,
    ) -> tuple[int, int]:
        """Compute deterministic hint levels from the gap between difficulty and effective level.

        New problem: hint = max(1, min(4, 1 + gap)), capped at 4.
        Same problem: previous hint + 1, capped at 5.
        """
        if same_problem:
            prog_hint = min(5, student_state.current_programming_hint_level + 1)
            maths_hint = min(5, student_state.current_maths_hint_level + 1)
        else:
            prog_gap = programming_difficulty - round(student_state.effective_programming_level)
            maths_gap = maths_difficulty - round(student_state.effective_maths_level)
            prog_hint = max(1, min(4, 1 + prog_gap))
            maths_hint = max(1, min(4, 1 + maths_gap))
        return prog_hint, maths_hint

    def coerce_stream_meta(
        self,
        raw_meta: dict[str, Any],
        *,
        student_state: StudentState,
        fast_signals: PedagogyFastSignals,
        source: str = "single_pass_header_route",
    ) -> StreamPedagogyMeta:
        """Normalise a raw metadata dict into a validated pedagogy metadata object."""

        same_problem = self._coerce_bool(raw_meta.get("same_problem"))
        is_elaboration = self._coerce_bool(raw_meta.get("is_elaboration"))
        prog = self._coerce_int(raw_meta.get("programming_difficulty"))
        maths = self._coerce_int(raw_meta.get("maths_difficulty"))
        if same_problem is None or is_elaboration is None:
            raise ValueError("Missing boolean metadata fields")
        if prog is None or maths is None:
            raise ValueError("Missing integer metadata fields")

        has_any_previous = bool(fast_signals.has_previous_exchange)
        if not has_any_previous:
            same_problem = False
            is_elaboration = False
        if not same_problem:
            is_elaboration = False

        clamped_prog = self._clamp_int(prog)
        clamped_maths = self._clamp_int(maths)
        prog_hint, maths_hint = self.compute_hint_levels(
            programming_difficulty=clamped_prog,
            maths_difficulty=clamped_maths,
            student_state=student_state,
            same_problem=same_problem,
        )

        return StreamPedagogyMeta(
            same_problem=same_problem,
            is_elaboration=is_elaboration,
            programming_difficulty=clamped_prog,
            maths_difficulty=clamped_maths,
            programming_hint_level=prog_hint,
            maths_hint_level=maths_hint,
            source=source,
        )

    def build_emergency_full_hint_fallback_meta(
        self,
        student_state: StudentState,
        fast_signals: PedagogyFastSignals,
    ) -> StreamPedagogyMeta:
        """Build a last-resort emergency metadata object when LLM metadata fails."""
        _ = fast_signals  # kept for call-site symmetry
        student_state.skip_next_ema_update_once = True
        programming_difficulty = round(student_state.effective_programming_level)
        maths_difficulty = round(student_state.effective_maths_level)

        return StreamPedagogyMeta(
            same_problem=False,
            is_elaboration=False,
            programming_difficulty=self._clamp_int(programming_difficulty),
            maths_difficulty=self._clamp_int(maths_difficulty),
            programming_hint_level=5,
            maths_hint_level=5,
            source="emergency_full_hint_fallback",
        )

    async def classify_two_step_recovery_meta(
        self,
        user_message: str,
        *,
        student_state: StudentState,
        fast_signals: PedagogyFastSignals,
    ) -> StreamPedagogyMeta:
        """Classify merged pedagogy metadata in one metadata-only LLM JSON call."""

        payload = self._build_two_step_recovery_payload(
            user_message=user_message,
            student_state=student_state,
            fast_signals=fast_signals,
        )
        try:
            response = await self.llm.generate(
                system_prompt=PEDAGOGY_TWO_STEP_RECOVERY_JSON_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=True)}],
                max_tokens=100,
            )
            raw_meta = self._parse_two_step_recovery_meta_response(response)
            if raw_meta is None:
                raise ValueError(f"Could not parse recovery-route metadata JSON: {response!r}")
            meta = self.coerce_stream_meta(
                raw_meta,
                student_state=student_state,
                fast_signals=fast_signals,
                source="two_step_recovery_route",
            )
            logger.info(
                "Pedagogy two-step-recovery metadata: same_problem=%s elaboration=%s prog=%d maths=%d prog_hint=%d maths_hint=%d",
                meta.same_problem,
                meta.is_elaboration,
                meta.programming_difficulty,
                meta.maths_difficulty,
                meta.programming_hint_level,
                meta.maths_hint_level,
            )
            return meta
        except Exception as exc:
            logger.warning(
                "Pedagogy two-step-recovery classification failed, using emergency fallback metadata: %s",
                exc,
            )
            return self.build_emergency_full_hint_fallback_meta(student_state, fast_signals)

    def apply_stream_meta(
        self,
        student_state: StudentState,
        meta: StreamPedagogyMeta,
    ) -> ProcessResult:
        """Apply validated stream metadata to the pedagogy state."""

        has_previous_exchange = bool(
            (student_state.last_question_text or "").strip()
            and (student_state.last_answer_text or "").strip()
        )
        if not meta.same_problem and has_previous_exchange:
            if student_state.skip_next_ema_update_once:
                student_state.skip_next_ema_update_once = False
            else:
                self._update_effective_levels(student_state)
            student_state.starting_programming_hint_level = meta.programming_hint_level
            student_state.starting_maths_hint_level = meta.maths_hint_level
        elif not meta.same_problem:
            student_state.starting_programming_hint_level = meta.programming_hint_level
            student_state.starting_maths_hint_level = meta.maths_hint_level

        student_state.current_programming_difficulty = self._clamp_int(meta.programming_difficulty)
        student_state.current_maths_difficulty = self._clamp_int(meta.maths_difficulty)
        student_state.current_programming_hint_level = self._clamp_int(meta.programming_hint_level)
        student_state.current_maths_hint_level = self._clamp_int(meta.maths_hint_level)

        return ProcessResult(
            programming_difficulty=student_state.current_programming_difficulty,
            maths_difficulty=student_state.current_maths_difficulty,
            programming_hint_level=student_state.current_programming_hint_level,
            maths_hint_level=student_state.current_maths_hint_level,
            is_same_problem=bool(meta.same_problem),
        )

    @staticmethod
    def _clamp_int(value: int) -> int:
        return max(1, min(5, int(value)))

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_bool(value: object) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalised = value.strip().lower()
            if normalised in {"true", "1", "yes", "y"}:
                return True
            if normalised in {"false", "0", "no", "n"}:
                return False
        return None

    def _build_two_step_recovery_payload(
        self,
        *,
        user_message: str,
        student_state: StudentState,
        fast_signals: PedagogyFastSignals,
    ) -> dict[str, Any]:
        """Build a compact payload for the two-step-recovery metadata classifier."""

        payload: dict[str, Any] = {
            # Keep the recovery-route metadata request compact. The full reply call still
            # sees the complete prompt context, so this metadata call only needs a trimmed
            # view of the current message.
            "current_message": self._truncate_text_tokens(user_message, max_tokens=320),
            "student_state": {
                "effective_programming_level": round(student_state.effective_programming_level, 2),
                "effective_maths_level": round(student_state.effective_maths_level, 2),
                "current_programming_difficulty": int(student_state.current_programming_difficulty),
                "current_maths_difficulty": int(student_state.current_maths_difficulty),
                "current_programming_hint_level": int(student_state.current_programming_hint_level),
                "current_maths_hint_level": int(student_state.current_maths_hint_level),
            },
            "has_previous_exchange": bool(fast_signals.has_previous_exchange),
        }
        if fast_signals.has_previous_exchange:
            payload["previous_question"] = self._truncate_text_tokens(
                fast_signals.previous_question_text or "",
                max_tokens=220,
            )
            payload["previous_answer"] = self._truncate_text_tokens(
                fast_signals.previous_answer_text or "",
                max_tokens=300,
            )
        return payload

    def _truncate_text_tokens(self, text: str, *, max_tokens: int) -> str:
        """Truncate a text block by approximate token count for metadata payloads."""
        clean = (text or "").strip()
        if not clean or max_tokens <= 0:
            return ""
        if self.llm.count_tokens(clean) <= max_tokens:
            return clean
        words = clean.split()
        kept: list[str] = []
        for word in words:
            candidate = " ".join(kept + [word])
            if self.llm.count_tokens(candidate) > max_tokens:
                break
            kept.append(word)
        return " ".join(kept)

    def _parse_two_step_recovery_meta_response(self, text: str) -> dict[str, Any] | None:
        """Parse a two-step-recovery metadata JSON response with a regex fallback."""

        try:
            data = json.loads((text or "").strip())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        if not isinstance(text, str) or not text:
            return None
        required_patterns = {
            "same_problem": r'"same_problem"\s*:\s*(true|false|"true"|"false")',
            "is_elaboration": r'"is_elaboration"\s*:\s*(true|false|"true"|"false")',
            "programming_difficulty": r'"programming_difficulty"\s*:\s*(\d+)',
            "maths_difficulty": r'"maths_difficulty"\s*:\s*(\d+)',
        }
        extracted: dict[str, Any] = {}
        for key, pattern in required_patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                return None
            raw = match.group(1).strip('"')
            if key in {"same_problem", "is_elaboration"}:
                value = self._coerce_bool(raw)
            else:
                value = self._coerce_int(raw)
            if value is None:
                return None
            extracted[key] = value
        if not extracted.get("same_problem"):
            extracted["is_elaboration"] = False
        return extracted

    @staticmethod
    def _update_effective_levels(student_state: StudentState) -> None:
        """Update effective levels using EMA based on previous problem performance.

        Each dimension uses its own hint level for independent calculation.
        """
        # --- Programming ---
        prog_hint = student_state.current_programming_hint_level
        prog_diff = student_state.current_programming_difficulty
        eff_prog = student_state.effective_programming_level

        prog_demonstrated = prog_diff * (6 - prog_hint) / 5
        prog_weight = min(1.0, prog_diff / max(eff_prog, 1.0))
        prog_lr = 0.2 * prog_weight

        new_prog = eff_prog * (1 - prog_lr) + prog_demonstrated * prog_lr
        student_state.effective_programming_level = max(1.0, min(5.0, new_prog))

        # --- Maths ---
        maths_hint = student_state.current_maths_hint_level
        maths_diff = student_state.current_maths_difficulty
        eff_maths = student_state.effective_maths_level

        maths_demonstrated = maths_diff * (6 - maths_hint) / 5
        maths_weight = min(1.0, maths_diff / max(eff_maths, 1.0))
        maths_lr = 0.2 * maths_weight

        new_maths = eff_maths * (1 - maths_lr) + maths_demonstrated * maths_lr
        student_state.effective_maths_level = max(1.0, min(5.0, new_maths))

        logger.info(
            "Updated effective levels: prog=%.2f, maths=%.2f",
            student_state.effective_programming_level,
            student_state.effective_maths_level,
        )

    def update_previous_exchange_text(
        self,
        student_state: StudentState,
        question: str,
        answer: str,
    ) -> None:
        """Store the previous Q+A text for LLM-only metadata routes."""
        student_state.last_question_text = question
        student_state.last_answer_text = answer
