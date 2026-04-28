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

"""Tests for adapter.ingestion_context — per-chat state machine."""

from __future__ import annotations

from adapter.directive_parser import DirectiveResult
from adapter.ingestion_context import IngestionContext


class TestIngestionContextActivation:
    """Tests for ACTIVE / INACTIVE state transitions."""

    def test_inactive_by_default(self) -> None:
        ctx = IngestionContext()
        assert ctx.is_active("chat-1") is False
        assert ctx.get_metadata("chat-1") is None

    def test_tag_start_activates(self) -> None:
        ctx = IngestionContext()
        directive = DirectiveResult(
            action="tag_start",
            metadata={"project": "Apollo"},
        )
        ctx.apply_directive("chat-1", directive)
        assert ctx.is_active("chat-1") is True
        assert ctx.get_metadata("chat-1") == {"project": "Apollo"}

    def test_tag_stop_deactivates(self) -> None:
        ctx = IngestionContext()
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"project": "X"},
        ))
        ctx.apply_directive("chat-1", DirectiveResult(action="tag_stop"))
        assert ctx.is_active("chat-1") is False
        assert ctx.get_metadata("chat-1") is None

    def test_none_directive_is_noop(self) -> None:
        ctx = IngestionContext()
        ctx.apply_directive("chat-1", DirectiveResult(action="none"))
        assert ctx.is_active("chat-1") is False


class TestMetadataReplacement:
    """Tests for FR2 — metadata replacement semantics."""

    def test_second_tag_start_replaces_metadata(self) -> None:
        ctx = IngestionContext()
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"project": "Alpha", "phase": "1"},
        ))
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"project": "Beta"},
        ))
        # Full replacement — "phase" key must be gone
        assert ctx.get_metadata("chat-1") == {"project": "Beta"}
        assert ctx.is_active("chat-1") is True

    def test_replacement_does_not_merge(self) -> None:
        ctx = IngestionContext()
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"a": "1", "b": "2"},
        ))
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"c": "3"},
        ))
        meta = ctx.get_metadata("chat-1")
        assert meta == {"c": "3"}
        assert "a" not in meta
        assert "b" not in meta


class TestKBIds:
    """Tests for KB ID management (independent of metadata state)."""

    def test_kb_ids_default_empty(self) -> None:
        ctx = IngestionContext()
        assert ctx.get_kb_ids("chat-1") == []

    def test_kb_ids_default_fallback(self) -> None:
        ctx = IngestionContext(default_kb_id="default-kb")
        assert ctx.get_kb_ids("chat-1") == ["default-kb"]

    def test_set_kb_ids(self) -> None:
        ctx = IngestionContext(default_kb_id="default-kb")
        ctx.set_kb_ids("chat-1", ["kb-1", "kb-2"])
        assert ctx.get_kb_ids("chat-1") == ["kb-1", "kb-2"]

    def test_kb_ids_persist_across_tag_stop(self) -> None:
        """KB IDs are independent of metadata state — they survive tag_stop."""
        ctx = IngestionContext()
        ctx.set_kb_ids("chat-1", ["kb-1"])
        ctx.apply_directive("chat-1", DirectiveResult(
            action="tag_start", metadata={"x": "y"},
        ))
        ctx.apply_directive("chat-1", DirectiveResult(action="tag_stop"))
        assert ctx.is_active("chat-1") is False
        assert ctx.get_kb_ids("chat-1") == ["kb-1"]

    def test_kb_ids_independent_per_chat(self) -> None:
        ctx = IngestionContext()
        ctx.set_kb_ids("chat-1", ["kb-a"])
        ctx.set_kb_ids("chat-2", ["kb-b"])
        assert ctx.get_kb_ids("chat-1") == ["kb-a"]
        assert ctx.get_kb_ids("chat-2") == ["kb-b"]


class TestIngestionPayload:
    """Tests for the combined ingestion payload."""

    def test_payload_when_active(self) -> None:
        ctx = IngestionContext()
        ctx.set_kb_ids("c1", ["kb-1"])
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"project": "X"},
        ))
        payload = ctx.get_ingestion_payload("c1")
        assert payload == {
            "kb_ids": ["kb-1"],
            "user_metadata": {"project": "X"},
        }

    def test_payload_when_inactive(self) -> None:
        ctx = IngestionContext(default_kb_id="dflt")
        payload = ctx.get_ingestion_payload("unknown-chat")
        assert payload == {
            "kb_ids": ["dflt"],
            "user_metadata": {},
        }

    def test_payload_after_tag_stop(self) -> None:
        ctx = IngestionContext()
        ctx.set_kb_ids("c1", ["kb-1"])
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"a": "b"},
        ))
        ctx.apply_directive("c1", DirectiveResult(action="tag_stop"))
        payload = ctx.get_ingestion_payload("c1")
        assert payload["user_metadata"] == {}
        assert payload["kb_ids"] == ["kb-1"]


class TestDebugInfo:
    """Tests for the debug introspection endpoint data."""

    def test_debug_info_no_context(self) -> None:
        ctx = IngestionContext()
        assert ctx.get_debug_info("unknown") is None

    def test_debug_info_active(self) -> None:
        ctx = IngestionContext()
        ctx.set_kb_ids("c1", ["kb-1"])
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"project": "Z"},
        ))
        info = ctx.get_debug_info("c1")
        assert info is not None
        assert info["chat_id"] == "c1"
        assert info["state"] == "ACTIVE"
        assert info["user_metadata"] == {"project": "Z"}
        assert info["kb_ids"] == ["kb-1"]
        assert "last_updated" in info


class TestClear:
    """Tests for context cleanup."""

    def test_clear_removes_all(self) -> None:
        ctx = IngestionContext()
        ctx.set_kb_ids("c1", ["kb-1"])
        ctx.apply_directive("c1", DirectiveResult(
            action="tag_start", metadata={"x": "y"},
        ))
        ctx.clear("c1")
        assert ctx.is_active("c1") is False
        assert ctx.get_metadata("c1") is None
        assert ctx.get_debug_info("c1") is None

    def test_clear_nonexistent_is_safe(self) -> None:
        ctx = IngestionContext()
        ctx.clear("does-not-exist")  # should not raise