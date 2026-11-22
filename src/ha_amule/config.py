"""App settings, read from the Supervisor's options file (or `AMULE_*` environment variables in dev)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

OPTIONS_FILE = Path("/data/options.json")


class Settings(BaseModel):
    download_dir: Path = Path("/share/amule/incoming")
    temp_dir: Path = Path("/share/amule/temp")
    share_dirs: list[Path] = Field(default_factory=list)
    nickname: str = "ha-amule"
    max_download_kbps: int = Field(default=0, ge=0)
    max_upload_kbps: int = Field(default=0, ge=0)
    connect_ed2k: bool = True
    connect_kad: bool = True
    servers_url: str = "http://upd.emule-security.org/server.met"
    nodes_url: str = "http://upd.emule-security.org/nodes.dat"
    remote_password: str = ""  # enables amulegui/amulecmd on port 4712 when set
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    # Not user options.
    data_dir: Path = Path("/data")
    amuled_binary: str = "amuled"
    tcp_port: int = 4662
    udp_port: int = 4672
    ec_port: int = 4712
    http_port: int = 8099
    ingress_only: bool = False  # the image sets it: answer only Ingress and the integration
    # Dev mode: talk to an amuled you started yourself instead of spawning one.
    ec_host: str | None = None
    ec_password: str | None = None

    @property
    def manage_daemon(self) -> bool:
        return self.ec_host is None

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "amule"


def load_settings(options_file: Path = OPTIONS_FILE) -> Settings:
    """Merge the Supervisor options file with `AMULE_*` environment variables (env wins)."""
    raw: dict[str, object] = {}
    if options_file.is_file():
        raw.update(json.loads(options_file.read_text()))
    for name in Settings.model_fields:
        value = os.environ.get(f"AMULE_{name.upper()}")
        if value is not None:
            raw[name] = json.loads(value) if name == "share_dirs" else value
    return Settings.model_validate(raw)
