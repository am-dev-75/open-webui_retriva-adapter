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

"""Tests for adapter.synthetic_response — OpenAI-compatible ack generation."""

from __future__ import annotations

from adapter.directive_parser import DirectiveResult
from adapter.turn_classifier import TurnClassification
from adapter.synthetic_response import build_response


def _make_classification(
    route: str,
    *,
    directive_action: str = "none",
    metadata: dict | None = None,
    filenames: list[str] | None = None,
) -> TurnClassification:
    directive = DirectiveResult(action=directive_action, metadata=metadata or {})
    return TurnClassification(
        has_directive=directive_action != "none",
        has_substantive_question=False,
        directive_result=directive,
        stripped_content="",
        route=route,
    )


class TestResponseShape:
    def _assert_valid(self, r: dict) -> None:
        assert r["id"].startswith("chatcmpl-adapter-")
        assert r["object"] == "chat.completion"
        assert r["model"] == "retriva-adapter"
        assert r["choices"][0]["finish_reason"] == "stop"
        assert r["choices"][0]["message"]["role"] == "assistant"
        assert r["usage"]["total_tokens"] == 0

    def test_directive_ack(self) -> None:
        self._assert_valid(build_response(_make_classification("directive_ack", directive_action="tag_start")))

    def test_directive_stop_ack(self) -> None:
        self._assert_valid(build_response(_make_classification("directive_stop_ack", directive_action="tag_stop")))

    def test_upload_ack(self) -> None:
        self._assert_valid(build_response(_make_classification("upload_ack", filenames=["t.pdf"])))

    def test_combined_ack(self) -> None:
        self._assert_valid(build_response(_make_classification("directive_plus_upload_ack", directive_action="tag_start", filenames=["d.pdf"])))


class TestContent:
    def test_directive_ack_content(self) -> None:
        c = _make_classification("directive_ack", directive_action="tag_start", metadata={"project": "Apollo"})
        txt = build_response(c)["choices"][0]["message"]["content"]
        assert "✅" in txt and "Apollo" in txt

    def test_stop_ack_content(self) -> None:
        txt = build_response(_make_classification("directive_stop_ack", directive_action="tag_stop"))["choices"][0]["message"]["content"]
        assert "🛑" in txt

    def test_upload_ack_content(self) -> None:
        txt = build_response(_make_classification("upload_ack"))["choices"][0]["message"]["content"]
        assert "✅ Document received" in txt

    def test_combined_content(self) -> None:
        c = _make_classification("directive_plus_upload_ack", directive_action="tag_start", metadata={"p": "X"})
        txt = build_response(c)["choices"][0]["message"]["content"]
        assert "✅ Document received" in txt and "X" in txt


class TestUniqueIds:
    def test_ids_differ(self) -> None:
        c = _make_classification("directive_ack", directive_action="tag_start")
        assert build_response(c)["id"] != build_response(c)["id"]