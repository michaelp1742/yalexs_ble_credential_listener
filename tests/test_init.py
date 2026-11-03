"""Tests for the Yale Access Bluetooth Credential Listener setup and lifecycle."""

import logging
from unittest.mock import Mock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from yalexs_ble import LockStatus

from custom_components.yalexs_ble_credential_listener import async_hook
from custom_components.yalexs_ble_credential_listener.attribution import LockAttributor
from custom_components.yalexs_ble_credential_listener.const import (
    EVENT_LOCK_ACTIVITY,
    OWNER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from . import (
    ADDRESS,
    FRONT_ADDRESS,
    FRONT_TITLE,
    REMOTE_UNLOCKED,
    async_advance,
    async_deliver,
    async_setup_owner,
    lock_status_change,
)


@pytest.mark.parametrize("attribution", [False])
async def test_option_off_leaves_entry_idle(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    hook: Mock,
    config_entry: MockConfigEntry,
) -> None:
    """With the option off, the entry loads and runs nothing for the lock."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    # Core's entry does not exist yet, and setup does not need it.
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is None

    owner_entry = await async_setup_owner(hass)
    lock = owner_entry.runtime_data.lock
    core_listener = Mock()
    owner_entry.async_on_state_change(core_listener)
    entry_listener = Mock()
    config_entry.async_on_state_change(entry_listener)
    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    core_listener.assert_called()
    entry_listener.assert_not_called()
    assert (
        er.async_entries_for_config_entry(entity_registry, config_entry.entry_id) == []
    )
    lock.register_log_record_callback.assert_not_called()
    hook.async_register_attributor.assert_not_called()
    assert await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.parametrize("has_hook", [False])
async def test_a_helpers_module_that_fails_its_imports_raises(
    hass: HomeAssistant,
) -> None:
    """Only an absent helpers module returns None; one that fails its own imports raises."""
    integration = await async_get_integration(hass, OWNER_DOMAIN)
    error = ImportError("cannot import name 'PushLock'", name="yalexs_ble")

    assert await async_hook(hass) is None
    with (
        patch.object(integration, "_import_platform", side_effect=error),
        pytest.raises(ImportError) as raised,
    ):
        await async_hook(hass)

    assert raised.value is error


async def test_setup_registers_the_reader_and_the_attributor_for_its_lock(
    hass: HomeAssistant, hook: Mock, config_entry: MockConfigEntry
) -> None:
    """Setup registers the attributor's reader on the lock's PushLock and the attributor with core."""
    await async_setup_owner(hass, FRONT_ADDRESS, FRONT_TITLE)
    owner_entry = await async_setup_owner(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)

    attributor = config_entry.runtime_data
    assert isinstance(attributor, LockAttributor)
    lock = owner_entry.runtime_data.lock
    lock.register_log_record_callback.assert_called_once_with(
        attributor.async_log_record
    )
    hook.async_register_attributor.assert_called_once_with(hass, ADDRESS, attributor)


async def test_unload_removes_the_registrations_and_the_settle_timer(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hook: Mock,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    config_entry: MockConfigEntry,
) -> None:
    """Unloading the entry removes the reader and the attributor and cancels the settle timer."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await async_advance(hass, freezer, 0.75)

    owner_entry.runtime_data.lock.register_log_record_callback.return_value.assert_called_once()
    hook.async_register_attributor.return_value.assert_called_once()
    assert change.sets == []
    assert events == []


@pytest.mark.parametrize("has_hook", [False])
async def test_option_on_without_the_hook_warns_and_registers_nothing(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    owner_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """With the option on and no hook in core's yalexs_ble, setup warns once and registers nothing."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is None
    (record,) = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components.yalexs_ble_credential_listener")
    ]
    assert record.levelno == logging.WARNING
    assert "async_register_attributor" in record.getMessage()
    owner_entry.runtime_data.lock.register_log_record_callback.assert_not_called()
    entry_listener = Mock()
    config_entry.async_on_state_change(entry_listener)
    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()
    entry_listener.assert_not_called()


async def test_core_unload_reloads_entry_until_core_loads(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Core's unload reloads the entry, which waits for core's next load."""
    old_lock = owner_entry.runtime_data.lock
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert config_entry.reason == "Yale Access Bluetooth has not loaded this lock"

    assert await hass.config_entries.async_setup(owner_entry.entry_id)
    await async_advance(hass, freezer, 6)

    assert config_entry.state is ConfigEntryState.LOADED
    new_lock = owner_entry.runtime_data.lock
    assert new_lock is not old_lock
    new_lock.register_log_record_callback.assert_called_once_with(
        config_entry.runtime_data.async_log_record
    )


async def test_core_change_reaches_the_next_listener(
    hass: HomeAssistant, owner_entry: MockConfigEntry, config_entry: MockConfigEntry
) -> None:
    """The entry's reload waits until core's entry has called every listener."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    seen: list[tuple[ConfigEntryState, ConfigEntryState]] = []
    owner_entry.async_on_state_change(
        lambda: seen.append((owner_entry.state, config_entry.state))
    )

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert seen == [
        (ConfigEntryState.UNLOAD_IN_PROGRESS, ConfigEntryState.LOADED),
        (ConfigEntryState.NOT_LOADED, ConfigEntryState.LOADED),
    ]
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_core_change_reloads_entry_once(
    hass: HomeAssistant, owner_entry: MockConfigEntry, config_entry: MockConfigEntry
) -> None:
    """Each reload or unload of core's entry reloads the entry once."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    states: list[ConfigEntryState] = []
    config_entry.async_on_state_change(lambda: states.append(config_entry.state))

    assert await hass.config_entries.async_reload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert states.count(ConfigEntryState.SETUP_IN_PROGRESS) == 1
    assert config_entry.state is ConfigEntryState.LOADED
    new_lock = owner_entry.runtime_data.lock
    new_lock.register_log_record_callback.assert_called_once_with(
        config_entry.runtime_data.async_log_record
    )

    assert await hass.config_entries.async_unload(owner_entry.entry_id)
    await hass.async_block_till_done()

    assert states.count(ConfigEntryState.SETUP_IN_PROGRESS) == 2
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
