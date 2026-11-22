"""Runs amuled: writes its configuration, starts it and restarts it if it dies."""

from __future__ import annotations

import asyncio
import configparser
import contextlib
import hashlib
import io
import logging
import secrets
import signal

from ha_amule.amule import is_noise
from ha_amule.config import Settings

log = logging.getLogger(__name__)
amuled_log = logging.getLogger("amuled")

STOP_TIMEOUT = 30  # amuled flushes part files on exit; give it time
RESTART_DELAYS = (2, 5, 15, 30, 60)


def ec_password(settings: Settings) -> str:
    """The user's remote password, or a random one kept in the data folder."""
    if settings.remote_password:
        return settings.remote_password
    path = settings.data_dir / "ec_password"
    if path.is_file() and len(key := path.read_text().strip()) >= 32:
        return key
    key = secrets.token_urlsafe(32)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(key)
    path.chmod(0o600)
    return key


def write_config(settings: Settings, password: str) -> None:
    """Create or update amule.conf with the options this app controls.

    amuled fills in everything else with its defaults and saves it on exit, so preferences
    changed through EC (or by hand) survive restarts unless they are managed here.
    """
    conf_dir = settings.config_dir
    conf_dir.mkdir(parents=True, exist_ok=True)
    for folder in (settings.download_dir, settings.temp_dir):
        folder.mkdir(parents=True, exist_ok=True)

    path = conf_dir / "amule.conf"
    parser = configparser.RawConfigParser(strict=False, delimiters=("=",))
    parser.optionxform = str  # type: ignore[assignment,method-assign]  # keys are case sensitive
    if path.is_file():
        parser.read(path, encoding="utf-8")

    def put(section: str, values: dict[str, object]) -> None:
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            parser.set(section, key, str(int(value) if isinstance(value, bool) else value))

    put(
        "eMule",
        {
            "Nick": settings.nickname,
            "Port": settings.tcp_port,
            "UDPPort": settings.udp_port,
            "UDPEnable": True,
            "TempDir": settings.temp_dir,
            "IncomingDir": settings.download_dir,
            "MaxDownload": settings.max_download_kbps,
            "MaxUpload": settings.max_upload_kbps,
            "ConnectToED2K": settings.connect_ed2k,
            "ConnectToKad": settings.connect_kad,
            "Autoconnect": True,
            "Reconnect": True,
            "Serverlist": True,  # refresh the server list from addresses.dat on start
            "Ed2kServersUrl": settings.servers_url,
            "KadNodesUrl": settings.nodes_url,
            "UPnPEnabled": False,  # the container can't reach the router's UPnP anyway
            "NewVersionCheck": False,
            "OSDirectory": conf_dir,
        },
    )
    put(
        "ExternalConnect",
        {
            "AcceptExternalConnections": True,
            # Only the app talks to EC unless the user asked for remote access.
            "ECAddress": "" if settings.remote_password else "127.0.0.1",
            "ECPort": settings.ec_port,
            "ECPassword": hashlib.md5(password.encode(), usedforsecurity=False).hexdigest(),
            "UPnPECEnabled": False,
        },
    )
    put("WebServer", {"Enabled": False})

    buffer = io.StringIO()
    parser.write(buffer, space_around_delimiters=False)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    path.chmod(0o600)

    (conf_dir / "addresses.dat").write_text(settings.servers_url + "\n" if settings.servers_url else "")
    shared = [str(d) for d in settings.share_dirs if d.is_dir()]
    (conf_dir / "shareddir.dat").write_text("".join(f"{d}\n" for d in shared))
    for missing in sorted(set(map(str, settings.share_dirs)) - set(shared)):
        log.warning("Shared folder %s does not exist; skipping it", missing)


class Daemon:
    def __init__(self, settings: Settings, password: str) -> None:
        self.settings = settings
        self.password = password
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def start(self) -> None:
        write_config(self.settings, self.password)
        self._task = asyncio.create_task(self._supervise(), name="amuled")

    async def stop(self) -> None:
        self._stopping = True
        process = self._process
        if process and process.returncode is None:
            process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT)
            except TimeoutError:
                log.warning("amuled did not stop in %ss; killing it", STOP_TIMEOUT)
                process.kill()
                await process.wait()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _supervise(self) -> None:
        failures = 0
        while not self._stopping:
            # A crash leaves the lock behind and amuled then refuses to start.
            (self.settings.config_dir / "muleLock").unlink(missing_ok=True)
            started = asyncio.get_running_loop().time()
            try:
                self._process = await asyncio.create_subprocess_exec(
                    self.settings.amuled_binary,
                    f"--config-dir={self.settings.config_dir}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as err:
                self.last_error = f"Cannot start amuled: {err}"
                log.error("%s", self.last_error)
                return
            log.info("amuled started (pid %s)", self._process.pid)
            await self._pump(self._process)
            code = await self._process.wait()
            if self._stopping:
                return
            self.last_error = f"amuled exited with code {code}"
            failures = 0 if asyncio.get_running_loop().time() - started > 300 else failures + 1
            delay = RESTART_DELAYS[min(failures, len(RESTART_DELAYS) - 1)]
            log.error("%s; restarting in %ss", self.last_error, delay)
            await asyncio.sleep(delay)

    async def _pump(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            return
        async for raw in process.stdout:
            line = raw.decode(errors="replace").rstrip()
            if is_noise(line):
                amuled_log.debug("%s", line)
            elif "ERROR" in line or "Error" in line:
                amuled_log.warning("%s", line)
            else:
                amuled_log.info("%s", line)
