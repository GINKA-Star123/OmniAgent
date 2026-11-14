from __future__ import annotations

import logging


class _SuppressMem0MainRecords(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def install_mem0_log_guard() -> None:
    """Suppress known Mem0 logger records, including body-bearing INFO messages."""
    logger = logging.getLogger("mem0.memory.main")
    if not any(isinstance(item, _SuppressMem0MainRecords) for item in logger.filters):
        logger.addFilter(_SuppressMem0MainRecords())
