"""Answer-quality seam for future field-specific validation."""

from logger import get_logger

logger = get_logger(__name__)


async def rate_answer(
    field_key: str,
    question: str,
    answer: str,
    classification: str,
) -> dict:
    """Return a non-blocking answer-quality verdict.

    Phase 1 intentionally mirrors the classifier result and logs only. Once the
    product rubric is defined, this function can be replaced with field-specific
    scoring without changing the workflow controller.
    """
    if classification == "deferred":
        verdict = "deferred"
    elif classification == "answered":
        verdict = "accepted"
    else:
        verdict = "needs_followup"

    result = {
        "verdict": verdict,
        "reason": "Phase 1 stub based on active-field classification.",
    }
    logger.info(
        "Answer quality stub: field=%s classification=%s verdict=%s",
        field_key,
        classification,
        verdict,
    )
    return result
