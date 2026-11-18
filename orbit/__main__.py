"""Run the ORBIT AI API with ``python -m orbit`` (development entry point)."""

from __future__ import annotations

import uvicorn

from orbit.api.app import create_app
from orbit.core.config import get_settings


def main() -> None:
    settings = get_settings()
    # log_config=None keeps uvicorn from reconfiguring the ORBIT logging stack.
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
