# SPDX-License-Identifier: MIT
"""Tests for adapter.turn_classifier — turn routing logic."""

from __future__ import annotations

from adapter.turn_classifier import classify


def _make_body(
    content: str = "",
    *,
    files: list | None = None,
    role: str = "user",
) -> dict:
    """Build a minimal chat completion request body."""
    body: dict = {
        "model": "test-model",
        "messages": [{"role": role, "content": content}],
    }
    if files is not None:
        body["files"] = files
    return body


class TestDirectiveOnlyRouting:
    """Directive-only turns → directive_ack / directive_stop_ack."""

    def test_tag_start_only(self) -> None:
        body = _make_body("@@ingestion_tag_start\nproject: Apollo")
        result = classify(body)
        assert result.route == "directive_ack"
        assert result.has_directive is True
        assert result.has_files is False
        assert result.has_substantive_question is False

    def test_tag_start_no_metadata(self) -> None:
        body = _make_body("@@ingestion_tag_start")
        result = classify(body)
        assert result.route == "directive_ack"

    def test_tag_stop_only(self) -> None:
        body = _make_body("@@ingestion_tag_stop")
        result = classify(body)
        assert result.route == "directive_stop_ack"
        assert result.has_directive is True
        assert result.has_files is False
        assert result.has_substantive_question is False

    def test_tag_start_case_insensitive(self) -> None:
        body = _make_body("@@INGESTION_TAG_START\nteam: Alpha")
        result = classify(body)
        assert result.route == "directive_ack"


class TestUploadOnlyRouting:
    """Upload-only turns → upload_ack."""

    def test_files_no_text(self) -> None:
        body = _make_body("", files=[{"filename": "report.pdf"}])
        result = classify(body)
        assert result.route == "upload_ack"
        assert result.has_files is True
        assert result.has_directive is False
        assert result.has_substantive_question is False
        assert result.filenames == ["report.pdf"]

    def test_files_with_trivial_text(self) -> None:
        """Short non-alphabetic text is not a substantive question."""
        body = _make_body("...", files=[{"filename": "data.csv"}])
        result = classify(body)
        assert result.route == "upload_ack"

    def test_multiple_files(self) -> None:
        body = _make_body(
            "",
            files=[
                {"filename": "a.pdf"},
                {"filename": "b.txt"},
                {"name": "c.md"},
            ],
        )
        result = classify(body)
        assert result.route == "upload_ack"
        assert len(result.filenames) == 3


class TestCombinedDirectiveUploadRouting:
    """Directive + files, no question → directive_plus_upload_ack."""

    def test_directive_plus_files(self) -> None:
        body = _make_body(
            "@@ingestion_tag_start\nproject: Beta",
            files=[{"filename": "spec.pdf"}],
        )
        result = classify(body)
        assert result.route == "directive_plus_upload_ack"
        assert result.has_directive is True
        assert result.has_files is True
        assert result.has_substantive_question is False


class TestForwardRouting:
    """Turns with substantive questions → forward."""

    def test_plain_question(self) -> None:
        body = _make_body("What is the project status?")
        result = classify(body)
        assert result.route == "forward"
        assert result.has_substantive_question is True

    def test_directive_plus_question(self) -> None:
        body = _make_body(
            "@@ingestion_tag_start\nproject: X\n\nWhat does this document say?",
        )
        result = classify(body)
        assert result.route == "forward"
        assert result.has_directive is True
        assert result.has_substantive_question is True

    def test_files_plus_question(self) -> None:
        body = _make_body(
            "Please summarise this document",
            files=[{"filename": "report.pdf"}],
        )
        result = classify(body)
        assert result.route == "forward"
        assert result.has_files is True
        assert result.has_substantive_question is True

    def test_all_three_signals(self) -> None:
        body = _make_body(
            "@@ingestion_tag_start\nproject: Z\n\nWhat is the key finding here?",
            files=[{"filename": "findings.pdf"}],
        )
        result = classify(body)
        assert result.route == "forward"
        assert result.has_directive is True
        assert result.has_files is True
        assert result.has_substantive_question is True


class TestEdgeCases:
    """Edge cases for turn classification."""

    def test_empty_message(self) -> None:
        body = _make_body("")
        result = classify(body)
        assert result.route == "forward"  # nothing to intercept

    def test_no_user_message(self) -> None:
        body = {
            "model": "test",
            "messages": [{"role": "system", "content": "You are helpful."}],
        }
        result = classify(body)
        assert result.route == "forward"

    def test_empty_messages_array(self) -> None:
        body = {"model": "test", "messages": []}
        result = classify(body)
        assert result.route == "forward"

    def test_files_as_string_ids(self) -> None:
        """Files specified as string IDs should still be detected."""
        body = _make_body("", files=["file-abc-123"])
        result = classify(body)
        assert result.route == "upload_ack"
        assert result.filenames == ["file-abc-123"]

    def test_stripped_content_excludes_directives(self) -> None:
        body = _make_body("@@ingestion_tag_start\nproject: X\n\nTell me about the data")
        result = classify(body)
        assert "@@ingestion_tag_start" not in result.stripped_content
        assert "Tell me about the data" in result.stripped_content
