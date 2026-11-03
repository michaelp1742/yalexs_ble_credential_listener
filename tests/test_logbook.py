"""Tests for the Yale Access Bluetooth Credential Listener logbook descriptions."""

from collections.abc import Callable
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yalexs_ble_credential_listener.const import (
    DOMAIN,
    EVENT_LOCK_ACTIVITY,
    OWNER_DOMAIN,
)
from custom_components.yalexs_ble_credential_listener.logbook import (
    async_describe_events,
)
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import ADDRESS, FRONT_TITLE, LOCK


def _describer(hass: HomeAssistant) -> Callable[[Event], dict[str, Any]]:
    """Return the logbook's describer of the lock activity event."""
    describers: dict[tuple[str, str], Callable[[Event], dict[str, Any]]] = {}
    async_describe_events(
        hass,
        lambda domain, event_type, describe: describers.update(
            {(domain, event_type): describe}
        ),
    )
    return describers[DOMAIN, EVENT_LOCK_ACTIVITY]


def _event(
    device_id: str | None,
    source: str = "pin",
    slot: int | None = 1,
    master_code: bool = False,
    changed_by: str = "Keypad slot 1",
) -> Event:
    """Return a lock activity event of the main lock."""
    return Event(
        EVENT_LOCK_ACTIVITY,
        {
            "device_id": device_id,
            "entity_id": LOCK,
            "source": source,
            "slot": slot,
            "master_code": master_code,
            "changed_by": changed_by,
        },
    )


@pytest.fixture
def lock_device(
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    owner_entry: MockConfigEntry,
) -> dr.DeviceEntry:
    """Register core's device for the lock, named as the bench's, with its lock entity."""
    device = device_registry.async_get_or_create(
        config_entry_id=owner_entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
        identifiers={(OWNER_DOMAIN, "serial")},
        name=FRONT_TITLE,
    )
    lock = entity_registry.async_get_or_create(
        LOCK_DOMAIN,
        OWNER_DOMAIN,
        ADDRESS,
        suggested_object_id="back_door",
        config_entry=owner_entry,
        device_id=device.id,
    )
    entity_registry.async_update_entity(lock.entity_id, name="Front Door Lock")
    return device


@pytest.mark.parametrize(
    ("source", "slot", "master_code", "changed_by", "message"),
    [
        pytest.param("pin", None, True, "Master code", "master code used", id="master"),
        pytest.param(
            "pin", 1, False, "Keypad slot 1", "keypad slot 1 used", id="keypad slot"
        ),
        pytest.param("pin", None, False, "Keypad", "keypad used", id="keypad"),
        pytest.param(
            "rf", 7, False, "RF tag slot 7", "RF tag slot 7 used", id="RF tag slot"
        ),
        pytest.param("manual", None, False, "Manual", "operated manually", id="manual"),
        pytest.param("auto_lock", None, False, "Auto lock", "auto locked", id="auto"),
        pytest.param("remote", None, False, "Remote", "operated remotely", id="remote"),
        pytest.param("future", None, False, "Future", "future", id="unknown source"),
    ],
)
async def test_logbook_describes_each_source(
    hass: HomeAssistant,
    lock_device: dr.DeviceEntry,
    source: str,
    slot: int | None,
    master_code: bool,
    changed_by: str,
    message: str,
) -> None:
    """The logbook describes each source of the lock activity event under the lock's device name."""
    description = _describer(hass)(
        _event(lock_device.id, source, slot, master_code, changed_by)
    )

    assert description == {"name": FRONT_TITLE, "message": message, "entity_id": LOCK}


async def test_logbook_names_the_entry_after_the_lock_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    lock_device: dr.DeviceEntry,
) -> None:
    """The entry's name is the device's name at the time it is described, not the lock entity's."""
    describe = _describer(hass)

    names = [describe(_event(lock_device.id))["name"]]
    device_registry.async_update_device(lock_device.id, name_by_user="Porch")
    names.append(describe(_event(lock_device.id))["name"])
    names.append(describe(_event("no_such_device"))["name"])
    names.append(describe(_event(None))["name"])

    assert names == [
        "Front Door",
        "Porch",
        "Yale Access Bluetooth lock",
        "Yale Access Bluetooth lock",
    ]
    assert describe(_event(lock_device.id))["message"] == "keypad slot 1 used"
