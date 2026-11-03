"""Tests for the attribution hook of a yalexs_ble loaded as a custom integration."""

from pathlib import Path
from unittest.mock import Mock, create_autospec, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockEntityPlatform,
    async_capture_events,
)
from yalexs_ble import LockStatus, PushLock

from custom_components.yalexs_ble_credential_listener import async_hook
from custom_components.yalexs_ble_credential_listener.attribution import LockAttributor
from custom_components.yalexs_ble_credential_listener.const import (
    EVENT_LOCK_ACTIVITY,
    OWNER_DOMAIN,
)
from homeassistant.components.lock import ATTR_CHANGED_BY, DOMAIN as LOCK_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from . import ADDRESS, CODE_SLOT_1_UNLOCKED, TITLE, UNITY, async_advance

HOOK_COPY = Path(__file__).parent / "hook"


@pytest.fixture(autouse=True)
def mock_owner_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load the yalexs_ble with the hook from custom_components, as an install that overrides core's does."""
    if not (HOOK_COPY / "custom_components" / "yalexs_ble").is_dir():
        pytest.skip(
            "no copy under tests/hook; script/build-hook-copy.sh builds the copy this test loads"
        )
    monkeypatch.syspath_prepend(HOOK_COPY)


def _lock_state(status: LockStatus) -> Mock:
    """Return a lock state with the fields the lock entities read."""
    return Mock(spec_set=["lock", "auth"], lock=status, auth=None)


async def test_hook_of_a_custom_yalexs_ble_reaches_its_lock_platform(
    hass: HomeAssistant,
) -> None:
    """async_hook returns the custom yalexs_ble's helpers, whose registrations its lock platform reads."""
    attributor = Mock()

    hook = await async_hook(hass)

    assert hook is not None
    assert hook.__name__ == "custom_components.yalexs_ble.helpers"
    hook.async_register_attributor(hass, ADDRESS.lower(), attributor)
    integration = await async_get_integration(hass, OWNER_DOMAIN)
    lock = await integration.async_get_platform("lock")
    assert lock.__name__ == "custom_components.yalexs_ble.lock"
    assert hass.data[lock.DATA_ATTRIBUTORS][ADDRESS] == [attributor]


async def test_the_hook_copys_lock_entities_write_the_change_with_the_listeners_cause(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The hook copy's YaleXSBLELock and YaleXSBLESecureModeLock write a change at once and then the attributor's cause, under the event's context."""
    hook = await async_hook(hass)
    assert hook is not None
    integration = await async_get_integration(hass, OWNER_DOMAIN)
    lock_platform = await integration.async_get_platform("lock")
    models = await integration.async_get_platform("models")
    options = models.LockOptions(
        unlatch=False,
        secure_mode=True,
        secure_mode_enabled=True,
        battery_reporting=False,
        activity_count=False,
        auto_lock=False,
        unlatch_hold_time=False,
    )
    push_lock = create_autospec(PushLock, instance=True, address=ADDRESS)
    push_lock.lock_state = _lock_state(LockStatus.LOCKED)
    push_lock.lock_info = Mock(
        manufacturer="Yale", model="model", serial="serial", firmware="1.0"
    )
    data = lock_platform.YaleXSBLEData(TITLE, push_lock, options, None)
    entities = [
        lock_platform.YaleXSBLELock(data),
        lock_platform.YaleXSBLESecureModeLock(data),
    ]
    with patch("homeassistant.components.bluetooth.async_track_unavailable"):
        await MockEntityPlatform(
            hass, domain=LOCK_DOMAIN, platform_name=OWNER_DOMAIN
        ).async_add_entities(entities)
    attributor = LockAttributor(hass, ADDRESS, UNITY)
    hook.async_register_attributor(hass, ADDRESS, attributor)
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    pushed_at = dt_util.utcnow()

    # The library passes one LockState to every lock entity for one report.
    new_state = _lock_state(LockStatus.UNLOCKED)
    for call in push_lock.register_callback.call_args_list:
        call.args[0](new_state, push_lock.lock_info, push_lock.connection_info)
    for entity in entities:
        state = hass.states.get(entity.entity_id)
        assert state.state == "unlocked"
        assert ATTR_CHANGED_BY not in state.attributes
    await async_advance(hass, freezer, 1.25)
    await attributor.async_log_record(CODE_SLOT_1_UNLOCKED, False)
    await async_advance(hass, freezer, 0.75)

    (event,) = events
    assert event.data["entity_id"] == entities[0].entity_id
    for entity in entities:
        state = hass.states.get(entity.entity_id)
        assert state.state == "unlocked"
        assert state.attributes[ATTR_CHANGED_BY] == "Keypad slot 1"
        assert state.context.id == event.context.id
        assert state.last_changed == pushed_at
        assert state.last_updated == dt_util.utcnow()
