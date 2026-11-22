from __future__ import annotations

import asyncio
import configparser
import hashlib
import os
import stat
from pathlib import Path

import pytest

from ha_amule import daemon
from ha_amule.config import Settings, load_settings
from ha_amule.daemon import Daemon, ec_password, write_config


def make_settings(tmp_path: Path, **changes: object) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        download_dir=tmp_path / "share/incoming",
        temp_dir=tmp_path / "share/temp",
        **changes,  # type: ignore[arg-type]
    )


def read_conf(settings: Settings) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read(settings.config_dir / "amule.conf")
    return parser


def test_ec_password_is_generated_once(tmp_path: Path) -> None:
    s = make_settings(tmp_path)
    first = ec_password(s)
    assert len(first) >= 32
    assert ec_password(s) == first
    assert stat.S_IMODE((s.data_dir / "ec_password").stat().st_mode) == 0o600
    assert ec_password(make_settings(tmp_path, remote_password="mine")) == "mine"


def test_write_config(tmp_path: Path) -> None:
    share = tmp_path / "videos"
    share.mkdir()
    s = make_settings(tmp_path, share_dirs=[share, tmp_path / "missing"], max_download_kbps=800, connect_kad=False)
    write_config(s, "pw")
    conf = read_conf(s)
    assert conf["eMule"]["IncomingDir"] == str(s.download_dir)
    assert conf["eMule"]["TempDir"] == str(s.temp_dir)
    assert conf["eMule"]["MaxDownload"] == "800"
    assert conf["eMule"]["ConnectToKad"] == "0"
    assert conf["eMule"]["Port"] == "4662"
    assert conf["ExternalConnect"]["ECAddress"] == "127.0.0.1"
    assert conf["ExternalConnect"]["ECPassword"] == hashlib.md5(b"pw").hexdigest()  # noqa: S324
    assert conf["WebServer"]["Enabled"] == "0"
    assert s.download_dir.is_dir() and s.temp_dir.is_dir()
    assert (s.config_dir / "shareddir.dat").read_text() == f"{share}\n"
    assert (s.config_dir / "addresses.dat").read_text() == f"{s.servers_url}\n"

    # Settings amuled saved itself survive; managed ones follow the options again.
    path = s.config_dir / "amule.conf"
    path.write_text(path.read_text().replace("[eMule]", "[eMule]\nQueueSizePref=99\nMaxDownload=5"))
    remote = make_settings(tmp_path, remote_password="pw")
    write_config(remote, "pw")
    conf = read_conf(remote)
    assert conf["eMule"]["QueueSizePref"] == "99"
    assert conf["eMule"]["MaxDownload"] == "0"
    assert conf["ExternalConnect"]["ECAddress"] == ""


def test_load_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    options = tmp_path / "options.json"
    options.write_text('{"nickname": "juan", "max_upload_kbps": 50, "share_dirs": ["/media/a"]}')
    monkeypatch.setenv("AMULE_MAX_UPLOAD_KBPS", "60")
    monkeypatch.setenv("AMULE_SHARE_DIRS", '["/share/b"]')
    s = load_settings(options)
    assert (s.nickname, s.max_upload_kbps, s.share_dirs) == ("juan", 60, [Path("/share/b")])
    assert s.manage_daemon
    assert load_settings(tmp_path / "missing.json").nickname == "ha-amule"


def fake_amuled(tmp_path: Path, script: str) -> str:
    path = tmp_path / "amuled"
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(0o755)
    return str(path)


async def test_daemon_runs_and_stops(tmp_path: Path) -> None:
    binary = fake_amuled(
        tmp_path,
        'echo "Initialising aMuleD"\necho "Assertion failed: noise"\necho "ERROR: real problem"\n'
        "trap 'exit 0' TERM\nwhile true; do sleep 0.1; done",
    )
    s = make_settings(tmp_path, amuled_binary=binary)
    d = Daemon(s, "pw")
    (s.config_dir).mkdir(parents=True)
    (s.config_dir / "muleLock").write_text("stale")
    d.start()
    for _ in range(50):
        if d.running:
            break
        await asyncio.sleep(0.05)
    assert d.running
    assert not (s.config_dir / "muleLock").exists()
    await d.stop()
    assert not d.running
    assert d.last_error is None


async def test_daemon_restarts_after_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "RESTART_DELAYS", (0.05,))
    counter = tmp_path / "starts"
    binary = fake_amuled(tmp_path, f"echo x >> {counter}\nexit 3")
    d = Daemon(make_settings(tmp_path, amuled_binary=binary), "pw")
    d.start()
    for _ in range(100):
        if counter.exists() and len(counter.read_text().splitlines()) >= 2:
            break
        await asyncio.sleep(0.05)
    await d.stop()
    assert len(counter.read_text().splitlines()) >= 2
    assert d.last_error == "amuled exited with code 3"


async def test_daemon_missing_binary(tmp_path: Path) -> None:
    d = Daemon(make_settings(tmp_path, amuled_binary=str(tmp_path / "nope")), "pw")
    d.start()
    await asyncio.sleep(0.1)
    await d.stop()
    assert d.last_error is not None and "Cannot start amuled" in d.last_error


async def test_daemon_killed_when_it_ignores_sigterm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon, "STOP_TIMEOUT", 0.2)
    binary = fake_amuled(tmp_path, "trap '' TERM\nwhile true; do sleep 0.1; done")
    d = Daemon(make_settings(tmp_path, amuled_binary=binary), "pw")
    d.start()
    for _ in range(50):
        if d.running:
            break
        await asyncio.sleep(0.05)
    await d.stop()
    assert not d.running
    assert os.name == "posix"
