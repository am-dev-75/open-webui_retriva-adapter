# SPDX-License-Identifier: MIT
"""Tests for OWUI synthetic prompt filtering."""

from adapter.turn_classifier import classify, is_human_authored_text


def _make_body(
    content: str,
    *,
    role: str = "user",
) -> dict:
    """Build a minimal chat completion request body."""
    return {
        "model": "test-model",
        "messages": [{"role": role, "content": content}],
    }


class TestHumanAuthoredTextFilter:
    def test_empty_string_is_not_human(self) -> None:
        assert not is_human_authored_text("")
        assert not is_human_authored_text("   \n ")

    def test_owui_markers_are_rejected(self) -> None:
        assert not is_human_authored_text("### Task:\nAnalyze something")
        assert not is_human_authored_text("Analyze the chat history to determine...")
        assert not is_human_authored_text("<chat_history>...")
        assert not is_human_authored_text("Strictly return in JSON format")

    def test_genuine_human_text_is_accepted(self) -> None:
        assert is_human_authored_text("Hello, how are you?")
        assert is_human_authored_text("Please summarize this document.")
        assert is_human_authored_text("What is the main point of section 3?")


class TestSyntheticPromptRouting:
    def test_synthetic_prompt_intercepted_inactive_context(self) -> None:
        """Synthetic prompt with inactive context must be intercepted as upload_ack."""
        body = _make_body("### Task:\nAnalyze the chat history")
        result = classify(body, is_ingestion_active=False)
        assert result.route == "upload_ack"
        assert result.has_substantive_question is False

    def test_synthetic_prompt_intercepted_active_context(self) -> None:
        """Synthetic prompt with active context must be intercepted as upload_ack."""
        body = _make_body("Strictly return in JSON format")
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"
        assert result.has_substantive_question is False

    def test_mixed_messages_uses_human_text(self) -> None:
        """If both synthetic and human texts exist, classification should rely on human text."""
        body = {
            "model": "test-model",
            "messages": [
                {"role": "user", "content": "What is the project status?"},
                {"role": "user", "content": "### Task:\nAnalyze the chat history"},
            ]
        }
        result = classify(body, is_ingestion_active=False)
        # It should forward because the human asked "What is the project status?"
        assert result.route == "forward"
        assert result.has_substantive_question is True

    def test_mixed_messages_upload_only(self) -> None:
        """If human text exists but is not a question, and tagging is ON, it's intercepted."""
        body = {
            "model": "test-model",
            "messages": [
                {"role": "user", "content": "Here is the document"},
                {"role": "user", "content": "<chat_history>"},
            ]
        }
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"
        assert result.has_substantive_question is False
