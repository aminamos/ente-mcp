"""Pure routing logic for the Ente NSFW classifier helper.

Kept free of torch/transformers so the ente-mcp test venv can import it.
"""

from __future__ import annotations

NSFW_THRESHOLD = 0.55
HIDDEN_ALBUM = ".hidden"

# Ensemble decisions that route to locked Hidden. "uncertain" hides too:
# mis-hiding a benign photo is safe, mis-exposing NSFW is not.
HIDDEN_DECISIONS = {"sensitive", "likely_sensitive", "uncertain"}


def classify_target(score: float, requested_album: str = "Inbox", threshold: float = NSFW_THRESHOLD) -> str:
    """Return the Ente album a file with this NSFW score should be queued to.

    NSFW (score >= threshold) always goes to locked Hidden; safe images go
    to the album the caller asked for.
    """
    if score >= threshold:
        return HIDDEN_ALBUM
    return requested_album


def classify_target_ensemble(
    decision: str,
    score: float,
    requested_album: str = "Inbox",
    threshold: float = NSFW_THRESHOLD,
) -> str:
    """Route on the full ensemble decision, falling back to the raw score.

    sensitive / likely_sensitive / uncertain -> locked Hidden; safe/likely_safe
    and score below threshold -> requested album.
    """
    if decision in HIDDEN_DECISIONS or score >= threshold:
        return HIDDEN_ALBUM
    return requested_album