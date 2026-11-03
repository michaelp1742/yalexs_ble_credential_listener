"""Tests for the Yale Access Bluetooth Credential Listener integration."""

from dataclasses import dataclass, field
from datetime import timedelta
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)
from yalexs_ble import LockState, LockStatus

from custom_components.yalexs_ble_credential_listener.const import OWNER_DOMAIN
from custom_components.yalexs_ble_credential_listener.models import LOCK_MODELS
from homeassistant.const import CONF_ADDRESS, STATE_UNKNOWN
from homeassistant.core import Context, HomeAssistant, callback

ADDRESS = "AA:BB:CC:DD:EE:FF"
TITLE = "Back Door"
FRONT_ADDRESS = "11:22:33:44:55:66"
FRONT_TITLE = "Front Door"

LOCK = "lock.back_door"
SECURE_MODE_LOCK = "lock.back_door_secure_mode"
MEDIAN = "sensor.back_door_attribution_time_median"
MAXIMUM = "sensor.back_door_attribution_time_maximum"
UNITY = next(model for model in LOCK_MODELS if model.key == "unity")

# Captured GetLog replies.
INSIDE_BUTTON_LOCKED = bytes.fromhex("bb2d00d4000c0500a7eedd6a1914190f0200")
END_OF_LOG = bytes.fromhex("bb2d00de800200009aa176a3a8a176a30200")
KEYPAD_INFO = bytes.fromhex("bb2d00c404922fe06ac30000008000000200")

# Constructed GetLog replies, each from a captured one with the bytes named
# changed and byte 3, the checksum, recomputed so the 18 bytes sum to 0
# modulo 256. A CodeOperation (0x07) at UNLOCKED, slot at bytes 14 and 15:
CODE_SLOT_1_UNLOCKED = bytes.fromhex("bb2d003e079aa176a333004bea1401000200")
CODE_SLOT_FFEE_UNLOCKED = bytes.fromhex("bb2d0052079aa176a333004bea14eeff0200")
# A CredentialOperation (0x0E), credential type at byte 9, slot at bytes 10 and
# 11, and the lock and door states or a credential error at byte 12:
RF_SLOT_7_UNLOCKED = bytes.fromhex("bb2d00770ef3f7e36a0107001337f2160200")
PIN_SLOT_3_UNLOCKED = bytes.fromhex("bb2d007c0ef3f7e36a0003001337f2160200")
INSIDE_DOOR_PIN_SLOT_FFEE_UNLOCKED = bytes.fromhex(
    "bb2d008d0ef3f7e36a05eeff1337f2160200"
)
FINGER_SLOT_8_UNLOCKED = bytes.fromhex("bb2d00750ef3f7e36a0208001337f2160200")
RF_SLOT_8_ERROR = bytes.fromhex("bb2d00960ef3f7e36a010800f337f2160200")
PIN_SLOT_3_ERROR = bytes.fromhex("bb2d009c0ef3f7e36a000300f337f2160200")
# A LockOperation (0x00), op_code at byte 5, lock state at byte 6, and
# key_slot at byte 7, from INSIDE_BUTTON_LOCKED:
AUTO_RELOCK_LOCKED = bytes.fromhex("bb2d00db00050500a7eedd6a1914190f0200")
REMOTE_UNLOCKED = bytes.fromhex("bb2d00e200000300a7eedd6a1914190f0200")
REMOTE_SECUREMODE = bytes.fromhex("bb2d00d900000c00a7eedd6a1914190f0200")
KEYPAD_BUTTON_LOCKED = bytes.fromhex("bb2d00e1000005ffa7eedd6a1914190f0200")
MANUAL_UNLOCKED = bytes.fromhex("bb2d00e100010300a7eedd6a1914190f0200")
ONE_TOUCH_LOCKED = bytes.fromhex("bb2d00d5000b0500a7eedd6a1914190f0200")
BLUETOOTH_RECEIVED_LOCKED = bytes.fromhex("bb2d00dd00030500a7eedd6a1914190f0200")


@dataclass(eq=False)
class LockStatusChangeDouble:
    """Stand in for core's LockStatusChange, with latest set by the test."""

    entity_id: str
    new_state: LockState
    commanded: bool = False
    latest: bool = True
    sets: list[tuple[str, Context | None]] = field(default_factory=list)

    @callback
    def async_set_changed_by(self, changed_by: str, context: Context | None) -> None:
        """Keep the set, which leaves latest as it is, as core's set does."""
        self.sets.append((changed_by, context))


def lock_state(status: LockStatus) -> Mock:
    """Return a lock state of status."""
    # The listener reads only lock, and the other fields of LockState differ
    # between yalexs-ble commits.
    return Mock(spec_set=["lock"], lock=status)


def lock_status_change(
    status: LockStatus, entity_id: str = LOCK, *, commanded: bool = False
) -> LockStatusChangeDouble:
    """Return a LockStatusChangeDouble of a change to status."""
    return LockStatusChangeDouble(entity_id, lock_state(status), commanded)


def sensor_reading(hass: HomeAssistant, entity_id: str) -> tuple[float | None, int]:
    """Return a sensor's value, None while it is unknown, and its samples attribute."""
    state = hass.states.get(entity_id)
    value = None if state.state == STATE_UNKNOWN else float(state.state)
    return value, state.attributes["samples"]


async def async_deliver(
    owner: MockConfigEntry, raw: bytes, *, backlog: bool = False
) -> None:
    """Hand a GetLog reply to the registered reader, as the library's drain does."""
    reader = owner.runtime_data.lock.register_log_record_callback.call_args.args[0]
    await reader(raw, backlog)


async def async_advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float
) -> None:
    """Move the clock on and run the timers that fall due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass)
    await hass.async_block_till_done()


async def async_setup_owner(
    hass: HomeAssistant, address: str = ADDRESS, title: str = TITLE
) -> MockConfigEntry:
    """Add and load an entry of core's yalexs_ble for one lock."""
    owner = MockConfigEntry(
        domain=OWNER_DOMAIN,
        title=title,
        data={CONF_ADDRESS: address},
        unique_id=address,
    )
    owner.add_to_hass(hass)
    assert await hass.config_entries.async_setup(owner.entry_id)
    return owner
