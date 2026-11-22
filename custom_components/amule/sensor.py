"""Transfer, queue and network sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfDataRate, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AmuleConfigEntry, AmuleCoordinator
from .entity import AmuleEntity

PARALLEL_UPDATES = 0  # the coordinator does all the polling

ED2K_STATES = ["high_id", "low_id", "connecting", "disconnected"]
KAD_STATES = ["connected", "firewalled", "connecting", "disconnected"]


@dataclass(frozen=True, kw_only=True)
class AmuleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], float | int | str | None]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _stat(name: str) -> Callable[[dict[str, Any]], int]:
    return lambda data: data["stats"][name]


def _count(name: str) -> Callable[[dict[str, Any]], int]:
    return lambda data: data["counts"][name]


def _ed2k(data: dict[str, Any]) -> str:
    c = data["status"]["connection"]
    if c["ed2k_connected"]:
        return "high_id" if c["ed2k_high_id"] else "low_id"
    return "connecting" if c["ed2k_connecting"] else "disconnected"


def _kad(data: dict[str, Any]) -> str:
    c = data["status"]["connection"]
    if c["kad_connected"]:
        return "firewalled" if c["kad_firewalled"] else "connected"
    return "connecting" if c["kad_running"] else "disconnected"


def _server(data: dict[str, Any]) -> str | None:
    server = data["status"]["connection"]["server"]
    return server["name"] if server else None


def _server_attrs(data: dict[str, Any]) -> dict[str, Any]:
    server = data["status"]["connection"]["server"] or {}
    return {"address": server.get("address"), "users": server.get("users"), "files": server.get("files")}


def _active_attrs(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "downloads": [
            {"name": d["name"], "progress": d["progress"], "speed": d["speed"], "size": d["size"]}
            for d in data["downloads"]
            if d["state"] == "downloading"
        ]
    }


def _rate(key: str, value_fn: Callable[[dict[str, Any]], int], unit: str) -> AmuleSensorDescription:
    return AmuleSensorDescription(
        key=key,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.BYTES_PER_SECOND,
        suggested_unit_of_measurement=unit,
        suggested_display_precision=1,
        value_fn=value_fn,
    )


def _total(key: str, value_fn: Callable[[dict[str, Any]], int]) -> AmuleSensorDescription:
    return AmuleSensorDescription(
        key=key,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,  # resets when amuled restarts
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=2,
        value_fn=value_fn,
    )


def _measure(key: str, value_fn: Callable[[dict[str, Any]], int], **kwargs: Any) -> AmuleSensorDescription:
    return AmuleSensorDescription(key=key, state_class=SensorStateClass.MEASUREMENT, value_fn=value_fn, **kwargs)


SENSORS: tuple[AmuleSensorDescription, ...] = (
    _rate("download_speed", _stat("download_speed"), UnitOfDataRate.MEGABYTES_PER_SECOND),
    _rate("upload_speed", _stat("upload_speed"), UnitOfDataRate.KILOBYTES_PER_SECOND),
    _measure("active_downloads", _count("downloading"), attrs_fn=_active_attrs),
    _measure("queued_downloads", _count("waiting")),
    _measure("paused_downloads", _count("paused")),
    _measure("completed_downloads", _count("completed")),
    _measure("failed_downloads", _count("error")),
    _measure("total_downloads", _count("total")),
    _measure("upload_queue", _stat("upload_queue")),
    _measure("shared_files", _stat("shared_files")),
    _measure("sources", _stat("sources"), entity_registry_enabled_default=False),
    _total("session_downloaded", _stat("total_received")),
    _total("session_uploaded", _stat("total_sent")),
    AmuleSensorDescription(key="ed2k_status", device_class=SensorDeviceClass.ENUM, options=ED2K_STATES, value_fn=_ed2k),
    AmuleSensorDescription(key="kad_status", device_class=SensorDeviceClass.ENUM, options=KAD_STATES, value_fn=_kad),
    AmuleSensorDescription(
        key="ed2k_server",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_server,
        attrs_fn=_server_attrs,
    ),
    _measure("ed2k_users", _stat("ed2k_users"), entity_category=EntityCategory.DIAGNOSTIC),
    _measure("kad_users", _stat("kad_users"), entity_category=EntityCategory.DIAGNOSTIC),
    _measure("kad_nodes", _stat("kad_nodes"), entity_category=EntityCategory.DIAGNOSTIC),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AmuleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(AmuleSensor(entry.runtime_data, description) for description in SENSORS)


class AmuleSensor(AmuleEntity, SensorEntity):
    entity_description: AmuleSensorDescription

    def __init__(self, coordinator: AmuleCoordinator, description: AmuleSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attrs_fn
        return attrs_fn(self.coordinator.data) if attrs_fn else None
