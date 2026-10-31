"""Tests for the Yale Access Bluetooth Credential Listener setup and lifecycle."""

from unittest.mock import Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yalexs_ble_credential_listener import async_seam
from custom_components.yalexs_ble_credential_listener.const import OWNER_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration

from . import async_setup_owner


@pytest.mark.parametrize("attribution", [False])
async def test_option_off_leaves_entry_idle(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    seam: Mock,
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
    seam.async_register_attributor.assert_not_called()
    assert await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.parametrize("has_seam", [False])
async def test_a_helpers_module_that_fails_its_imports_raises(
    hass: HomeAssistant,
) -> None:
    """Only an absent helpers module returns None; one that fails its own imports raises."""
    integration = await async_get_integration(hass, OWNER_DOMAIN)
    error = ImportError("cannot import name 'PushLock'", name="yalexs_ble")

    assert await async_seam(hass) is None
    with (
        patch.object(integration, "_import_platform", side_effect=error),
        pytest.raises(ImportError) as raised,
    ):
        await async_seam(hass)

    assert raised.value is error
