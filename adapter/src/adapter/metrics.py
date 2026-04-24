# SPDX-License-Identifier: MIT
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

directives_processed_total = Counter(
    "adapter_directives_processed_total",
    "Total directives parsed from chat messages",
    ["action"],
)

webhook_messages_total = Counter(
    "adapter_webhook_messages_total",
    "Total chat messages received via webhook",
)

chat_messages_observed_total = Counter(
    "adapter_chat_messages_observed_total",
    "Total user chat messages observed via chat polling",
)
