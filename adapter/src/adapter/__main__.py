# SPDX-License-Identifier: MIT
"""CLI entry point — run with ``python -m adapter``."""

import uvicorn

from adapter.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "adapter.main:app",
        host="0.0.0.0",  # noqa: S104
        port=settings.ADAPTER_PORT,
        log_level="warning",  # structlog handles app logging
    )


if __name__ == "__main__":
    main()
