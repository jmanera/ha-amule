"""Base entity: everything hangs off one "aMule" service device."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AmuleCoordinator


class AmuleEntity(CoordinatorEntity[AmuleCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AmuleCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        status = coordinator.data["status"]
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="aMule",
            manufacturer="aMule",
            model=f"amuled {status.get('amule_version') or ''}".strip(),
            sw_version=status["version"],
            entry_type=DeviceEntryType.SERVICE,
        )
