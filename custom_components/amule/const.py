"""Constants for the aMule integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "amule"
DEFAULT_PORT: Final = 8099
SCAN_INTERVAL: Final = timedelta(seconds=10)

EVENT_DOWNLOAD_COMPLETED: Final = f"{DOMAIN}_download_completed"
EVENT_DOWNLOAD_FAILED: Final = f"{DOMAIN}_download_failed"

SERVICE_ADD_LINK: Final = "add_link"
ATTR_LINK: Final = "link"
