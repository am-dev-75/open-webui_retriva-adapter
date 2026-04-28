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

"""Prometheus metrics for the adapter."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

files_synced_total = Counter(
    "adapter_files_synced_total",
    "Total files successfully synced to Retriva",
)

files_deleted_total = Counter(
    "adapter_files_deleted_total",
    "Total files successfully deleted from Retriva",
)

sync_errors_total = Counter(
    "adapter_sync_errors_total",
    "Total sync errors (ingestion or deletion failures)",
)

poll_duration_seconds = Histogram(
    "adapter_poll_duration_seconds",
    "Duration of a single poll-and-sync cycle in seconds",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120),
)

turns_intercepted_total = Counter(
    "adapter_turns_intercepted_total",
    "Total turns intercepted (not forwarded to LLM)",
    ["route"],
)

turns_forwarded_total = Counter(
    "adapter_turns_forwarded_total",
    "Total turns forwarded to the upstream LLM",
)