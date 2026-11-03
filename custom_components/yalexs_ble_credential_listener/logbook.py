"""Describe Yale Access Bluetooth Credential Listener logbook events."""

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import (
    ATTR_MASTER_CODE,
    ATTR_SLOT,
    ATTR_SOURCE,
    EVENT_LOCK_ACTIVITY,
    OWNER_DOMAIN,
    SOURCE_AUTO_LOCK,
    SOURCE_MANUAL,
    SOURCE_PIN,
    SOURCE_REMOTE,
    SOURCE_RF,
)

DEFAULT_NAME = "Yale Access Bluetooth lock"

MESSAGE_BY_SOURCE = {
    SOURCE_MANUAL: "operated manually",
    SOURCE_AUTO_LOCK: "auto locked",
    SOURCE_REMOTE: "operated remotely",
}


def _message(source: str, slot: int | None, master_code: bool) -> str:
    """Return the logbook message for a lock activity."""
    if source == SOURCE_RF:
        return f"RF tag slot {slot} used"
    if source != SOURCE_PIN:
        return MESSAGE_BY_SOURCE.get(source, source)
    if master_code:
        return "master code used"
    if slot is None:
        return "keypad used"
    return f"keypad slot {slot} used"


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe logbook events."""
    device_registry = dr.async_get(hass)

    @callback
    def async_describe_lock_activity(event: Event) -> dict[str, str]:
        """Describe a lock activity event under the name of the lock's device."""
        data = event.data
        device = device_registry.async_get(data[ATTR_DEVICE_ID])
        name = (device.name_by_user or device.name) if device else None
        return {
            LOGBOOK_ENTRY_NAME: name or DEFAULT_NAME,
            LOGBOOK_ENTRY_MESSAGE: _message(
                data[ATTR_SOURCE], data[ATTR_SLOT], data[ATTR_MASTER_CODE]
            ),
            LOGBOOK_ENTRY_ENTITY_ID: data[ATTR_ENTITY_ID],
        }

    # Described under yalexs_ble, since the logbook of an entity or device keeps only
    # the events of its config entries' domains, and the lock is yalexs_ble's.
    async_describe_event(
        OWNER_DOMAIN, EVENT_LOCK_ACTIVITY, async_describe_lock_activity
    )
