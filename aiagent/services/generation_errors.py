from __future__ import annotations


class GenerationUnavailableError(RuntimeError):
    code = "generation_unavailable"

    def __init__(self) -> None:
        super().__init__(self.code)
