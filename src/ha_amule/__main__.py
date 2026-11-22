"""Entry point: `ha-amule` / `python -m ha_amule`."""

from __future__ import annotations

import logging

import uvicorn

from ha_amule.api import create_app
from ha_amule.config import load_settings


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    uvicorn.run(
        create_app(settings),
        # Only Ingress and the keyed integration get in (see api.py).
        host="0.0.0.0",  # noqa: S104  # nosec B104
        port=settings.http_port,
        log_level=settings.log_level,
        access_log=settings.log_level == "debug",
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
