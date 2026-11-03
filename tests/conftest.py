"""Fixtures for the Yale Access Bluetooth Credential Listener tests."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, create_autospec

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_config_flow,
    mock_integration,
    mock_platform,
)
from yalexs_ble import PushLock

from custom_components.yalexs_ble_credential_listener.attribution import LockAttributor
from custom_components.yalexs_ble_credential_listener.const import (
    CONF_ATTRIBUTION,
    CONF_LOCK_MODEL,
    DOMAIN,
    OWNER_DOMAIN,
)
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import ADDRESS, TITLE, async_setup_owner


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in every test."""


async def _async_setup_owner_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load core's entry with a new PushLock, as core does on every load."""
    entry.runtime_data = Mock(
        lock=create_autospec(PushLock, instance=True, address=entry.data[CONF_ADDRESS])
    )
    return True


class _OwnerConfigFlow(ConfigFlow):
    """Stand in for the config flow of core's yalexs_ble."""


@pytest.fixture
def has_hook() -> bool:
    """Return whether core's yalexs_ble has the attribution hook."""
    return True


@pytest.fixture
def hook() -> Mock:
    """Return a stand-in for the helpers module of core's yalexs_ble."""
    return Mock(spec_set=["async_register_attributor"])


@pytest.fixture(autouse=True)
def mock_owner_integration(
    hass: HomeAssistant, has_hook: bool, hook: Mock
) -> Iterator[None]:
    """Stand in for core's yalexs_ble, which needs Bluetooth."""
    mock_integration(
        hass,
        MockModule(
            OWNER_DOMAIN,
            async_setup_entry=_async_setup_owner_entry,
            async_unload_entry=AsyncMock(return_value=True),
        ),
    )
    mock_platform(hass, f"{OWNER_DOMAIN}.config_flow")
    if has_hook:
        mock_platform(hass, f"{OWNER_DOMAIN}.helpers", hook)
    with mock_config_flow(OWNER_DOMAIN, _OwnerConfigFlow):
        yield


@pytest.fixture
async def owner_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return a loaded entry of core's yalexs_ble."""
    return await async_setup_owner(hass)


@pytest.fixture
def attribution() -> bool:
    """Return the attribution option of the listener entry."""
    return True


@pytest.fixture
def lock_model() -> str:
    """Return the lock_model option of the listener entry."""
    return "unity"


@pytest.fixture
def config_entry(
    hass: HomeAssistant, attribution: bool, lock_model: str
) -> MockConfigEntry:
    """Return the listener entry for the lock, not yet set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data={CONF_ADDRESS: ADDRESS},
        options={CONF_ATTRIBUTION: attribution, CONF_LOCK_MODEL: lock_model},
        unique_id=ADDRESS,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def core_lock(
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    owner_entry: MockConfigEntry,
) -> er.RegistryEntry:
    """Register the main lock entity of core's entry on core's device."""
    device = device_registry.async_get_or_create(
        config_entry_id=owner_entry.entry_id,
        connections={(dr.CONNECTION_BLUETOOTH, ADDRESS)},
        identifiers={(OWNER_DOMAIN, "serial")},
    )
    return entity_registry.async_get_or_create(
        LOCK_DOMAIN,
        OWNER_DOMAIN,
        ADDRESS,
        suggested_object_id="back_door",
        config_entry=owner_entry,
        device_id=device.id,
    )


@pytest.fixture
async def attributor(
    hass: HomeAssistant, core_lock: er.RegistryEntry, config_entry: MockConfigEntry
) -> LockAttributor:
    """Return the attributor of the loaded listener entry."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert isinstance(config_entry.runtime_data, LockAttributor)
    return config_entry.runtime_data
