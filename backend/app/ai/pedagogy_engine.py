import logging
from dataclasses import dataclass, field
from typing import Optional

from app.ai.difficulty_classifier import classify_difficulty
from app.ai.embedding_service import EmbeddingService
from app.ai.llm_base import LLMProvider
from app.ai.same_problem_classifier import classify_same_problem

logger = logging.getLogger(__name__)


@dataclass
class StudentState:
    user_id: str
    effective_programming_level: float
    effective_maths_level: float
    current_hint_level: int = 1
    starting_hint_level: int = 1
    current_programming_difficulty: int = 3
    current_maths_difficulty: int = 3
    last_question_text: Optional[str] = field(default=None, repr=False)
    last_answer_text: Optional[str] = field(default=None, repr=False)
    last_context_embedding: Optional[list[float]] = field(default=None, repr=False)


@dataclass
class ProcessResult:
    filter_result: Optional[str] = None  # "greeting", "off_topic", or None
    canned_response: Optional[str] = None
    hint_level: Optional[int] = None
    programming_difficulty: Optional[int] = None
    maths_difficulty: Optional[int] = None
    is_same_problem: bool = False


class PedagogyEngine:
    def __init__(
        self,
        embedding_service: EmbeddingService,
        llm: LLMProvider,
        same_problem_detection_mode: str = "llm",
    ):
        self.embedding_service = embedding_service
        self.llm = llm
        mode = (same_problem_detection_mode or "llm").strip().lower()
        self.same_problem_detection_mode = mode if mode in {"llm", "embedding"} else "llm"

    async def process_message(
        self,
        user_message: str,
        student_state: StudentState,
        username: str = "there",
        embedding_override: list[float] | None = None,
        enable_greeting_filter: bool = False,
        enable_off_topic_filter: bool = False,
    ) -> ProcessResult:
        """Process a user message through the pre-filter pipeline and pedagogy logic.

        Embeds the message exactly once, then runs all checks on the vector.
        """

        # 1. Embed the user message (single API call)
        embedding = embedding_override or await self.embedding_service.embed_text(
            user_message
        )

        if embedding:
            # 2. Check greeting — synchronous, no API call
            if enable_greeting_filter and self.embedding_service.check_greeting(embedding):
                return ProcessResult(
                    filter_result="greeting",
                    canned_response=(
                        f"Hello {username}! I am your AI coding tutor. "
                        "Ask me a question about programming, mathematics, or physics "
                        "and I will guide you through it."
                    ),
                )

            # 3. Check off-topic — synchronous, no API call
            if enable_off_topic_filter and self.embedding_service.check_off_topic(embedding):
                return ProcessResult(
                    filter_result="off_topic",
                    canned_response=(
                        "I can only help with programming, mathematics, and science questions. "
                        "Please ask me something related to these subjects."
                    ),
                )

        # 4. Same-problem detection
        #    Default path: LLM classifier over previous Q+A + current message.
        #    Optional path: embedding similarity + elaboration anchors.
        is_same_problem = False
        is_elaboration = False
        embedding_fallback_same_problem = False
        embedding_fallback_is_elaboration = False
        if student_state.last_context_embedding is not None and embedding:
            if self.embedding_service.check_same_problem(
                embedding, student_state.last_context_embedding
            ):
                embedding_fallback_same_problem = True
            elif self.embedding_service.check_elaboration_request(embedding):
                embedding_fallback_same_problem = True
                embedding_fallback_is_elaboration = True
        has_previous_exchange = bool(
            (student_state.last_question_text or "").strip()
            and (student_state.last_answer_text or "").strip()
        )
        if has_previous_exchange:
            if self.same_problem_detection_mode == "llm":
                llm_same, llm_elaboration = await classify_same_problem(
                    self.llm,
                    current_message=user_message,
                    previous_question=student_state.last_question_text or "",
                    previous_answer=student_state.last_answer_text or "",
                    fallback_same_problem=embedding_fallback_same_problem,
                    fallback_is_elaboration=embedding_fallback_is_elaboration,
                )
                is_same_problem = llm_same
                is_elaboration = llm_elaboration
            else:
                is_same_problem = embedding_fallback_same_problem
                is_elaboration = embedding_fallback_is_elaboration
        elif student_state.last_context_embedding is not None and embedding:
            # Safety fallback when old in-memory state has an embedding but not text context.
            is_same_problem = embedding_fallback_same_problem
            is_elaboration = embedding_fallback_is_elaboration

        if is_same_problem:
            # Increment hint level (cap at 5)
            hint_level = min(5, student_state.current_hint_level + 1)
            prog_diff = student_state.current_programming_difficulty
            maths_diff = student_state.current_maths_difficulty

            # Substantive follow-ups (caught by Q+A similarity) re-classify difficulty.
            # Generic elaboration requests keep difficulty.
            if not is_elaboration:
                prog_diff, maths_diff = await classify_difficulty(
                    self.llm,
                    user_message,
                    fallback_programming=prog_diff,
                    fallback_maths=maths_diff,
                    previous_question=student_state.last_question_text,
                    previous_answer=student_state.last_answer_text,
                    same_problem_context=True,
                )
        else:
            # New problem: update effective levels from previous interaction
            if student_state.last_context_embedding is not None or has_previous_exchange:
                self._update_effective_levels(student_state)

            # Classify difficulty via LLM
            prog_diff, maths_diff = await classify_difficulty(
                self.llm,
                user_message,
                fallback_programming=round(student_state.effective_programming_level),
                fallback_maths=round(student_state.effective_maths_level),
            )

            # Starting hint level based on the harder dimension
            prog_gap = prog_diff - round(student_state.effective_programming_level)
            maths_gap = maths_diff - round(student_state.effective_maths_level)
            gap = max(prog_gap, maths_gap)
            hint_level = max(1, min(4, 1 + gap))
            student_state.starting_hint_level = hint_level

        # 5. Update student state
        student_state.current_hint_level = hint_level
        student_state.current_programming_difficulty = prog_diff
        student_state.current_maths_difficulty = maths_diff
        # Context embedding is updated after the LLM response via update_context_embedding()

        return ProcessResult(
            hint_level=hint_level,
            programming_difficulty=prog_diff,
            maths_difficulty=maths_diff,
            is_same_problem=is_same_problem,
        )

    @staticmethod
    def _update_effective_levels(student_state: StudentState) -> None:
        """Update effective levels using EMA based on previous problem performance.

        Programming difficulty updates effective_programming_level.
        Maths difficulty updates effective_maths_level.
        """
        final_hint = student_state.current_hint_level

        # --- Programming ---
        prog_diff = student_state.current_programming_difficulty
        eff_prog = student_state.effective_programming_level

        prog_demonstrated = prog_diff * (6 - final_hint) / 5
        prog_weight = min(1.0, prog_diff / max(eff_prog, 1.0))
        prog_lr = 0.2 * prog_weight

        new_prog = eff_prog * (1 - prog_lr) + prog_demonstrated * prog_lr
        student_state.effective_programming_level = max(1.0, min(5.0, new_prog))

        # --- Maths ---
        maths_diff = student_state.current_maths_difficulty
        eff_maths = student_state.effective_maths_level

        maths_demonstrated = maths_diff * (6 - final_hint) / 5
        maths_weight = min(1.0, maths_diff / max(eff_maths, 1.0))
        maths_lr = 0.2 * maths_weight

        new_maths = eff_maths * (1 - maths_lr) + maths_demonstrated * maths_lr
        student_state.effective_maths_level = max(1.0, min(5.0, new_maths))

        logger.info(
            "Updated effective levels: prog=%.2f, maths=%.2f",
            student_state.effective_programming_level,
            student_state.effective_maths_level,
        )

    async def update_context_embedding(
        self,
        student_state: StudentState,
        question: str,
        answer: str,
        question_embedding: list[float] | None = None,
    ) -> None:
        """Embed the concatenated Q+A and store as context for same-problem detection.

        Called after each LLM-generated response (not after canned responses).
        The combined text gives richer topic context than the question alone.
        """
        answer_embedding = await self.embedding_service.embed_text(answer)
        if question_embedding and answer_embedding:
            embedding = self.embedding_service.combine_embeddings(
                [question_embedding, answer_embedding]
            )
        elif question_embedding:
            embedding = question_embedding
        else:
            combined = question + "\n" + answer
            embedding = await self.embedding_service.embed_text(combined)
        if embedding:
            student_state.last_context_embedding = embedding
        student_state.last_question_text = question
        student_state.last_answer_text = answer
