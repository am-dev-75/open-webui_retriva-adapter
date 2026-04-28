# Copyright (C) 2026 Andrea Marson (am.dev.75@gmail.com)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for adapter.turn_classifier — turn routing logic."""

from __future__ import annotations

from adapter.turn_classifier import classify


def _make_body(
    content: str = "",
    *,
    role: str = "user",
) -> dict:
    """Build a minimal chat completion request body."""
    return {
        "model": "test-model",
        "messages": [{"role": role, "content": content}],
    }


class TestDirectiveOnlyRouting:
    """Directive-only turns with no question → directive_plus_upload_ack OR directive_ack.
    Wait, tag_start with NO question results in directive_plus_upload_ack because context becomes active."""

    def test_tag_start_only(self) -> None:
        body = _make_body("@@ingestion_tag_start\nproject: Apollo")
        result = classify(body)
        # Because it starts ingestion, and there's no question, it's considered upload-only
        assert result.route == "directive_plus_upload_ack"
        assert result.has_directive is True
        assert result.has_substantive_question is False

    def test_tag_stop_only(self) -> None:
        body = _make_body("@@ingestion_tag_stop")
        result = classify(body, is_ingestion_active=True)
        # Stops ingestion, no question -> directive_stop_ack
        assert result.route == "directive_stop_ack"
        assert result.has_directive is True
        assert result.has_substantive_question is False


class TestUploadOnlyRouting:
    """Upload-only turns → upload_ack (empty/trivial text + active context)."""

    def test_empty_text_active_context(self) -> None:
        body = _make_body("")
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"
        assert result.has_directive is False
        assert result.has_substantive_question is False

    def test_trivial_text_active_context(self) -> None:
        body = _make_body("...")
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"

    def test_placeholder_text_active_context(self) -> None:
        body = _make_body("Here is the document")
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"
        assert result.has_substantive_question is False

    def test_json_placeholder_active_context(self) -> None:
        body = _make_body('{"file_id": "123", "name": "doc.pdf"}')
        result = classify(body, is_ingestion_active=True)
        assert result.route == "upload_ack"
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

    def test_question_with_active_context(self) -> None:
        body = _make_body("Please summarise this document")
        result = classify(body, is_ingestion_active=True)
        assert result.route == "forward"
        assert result.has_substantive_question is True


class TestEdgeCases:
    """Edge cases for turn classification."""

    def test_empty_message_inactive_context(self) -> None:
        body = _make_body("")
        result = classify(body, is_ingestion_active=False)
        assert result.route == "upload_ack"  # completely empty -> intercepted

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

    def test_stripped_content_excludes_directives(self) -> None:
        body = _make_body("@@ingestion_tag_start\nproject: X\n\nTell me about the data")
        result = classify(body)
        assert "@@ingestion_tag_start" not in result.stripped_content
        assert "Tell me about the data" in result.stripped_content