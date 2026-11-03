"""Attribution time sensors for the Yale Access Bluetooth Credential Listener integration."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import statistics
from typing import TYPE_CHECKING, Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import CONF_ADDRESS, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import YaleXSBLECredentialListenerConfigEntry
from .attribution import LockAttributor

ATTR_SAMPLES = "samples"


@dataclass(frozen=True, kw_only=True)
class AttributionTimeSensorEntityDescription(SensorEntityDescription):
    """Describes an attribution time sensor by the statistic it shows."""

    value_fn: Callable[[Sequence[float]], float]


SENSORS = (
    AttributionTimeSensorEntityDescription(
        key="attribution_time_median",
        translation_key="attribution_time_median",
        value_fn=statistics.median,
    ),
    AttributionTimeSensorEntityDescription(
        key="attribution_time_maximum",
        translation_key="attribution_time_maximum",
        value_fn=max,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YaleXSBLECredentialListenerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the attribution time sensors."""
    if TYPE_CHECKING:
        assert entry.runtime_data is not None
    async_add_entities(
        AttributionTimeSensor(entry.data[CONF_ADDRESS], entry.runtime_data, description)
        for description in SENSORS
    )


class AttributionTimeSensor(SensorEntity):
    """A statistic of the times from a lock change to the set of its cause."""

    entity_description: AttributionTimeSensorEntityDescription

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 2
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        address: str,
        attributor: LockAttributor,
        description: AttributionTimeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._attributor = attributor
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)}
        )

    @override
    async def async_added_to_hass(self) -> None:
        """Write the state after each time the attributor adds."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._attributor.async_add_time_listener(self.async_write_ha_state)
        )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the statistic of the times, or None before the first."""
        times = self._attributor.times
        return self.entity_description.value_fn(times) if times else None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the count of times."""
        return {ATTR_SAMPLES: len(self._attributor.times)}
