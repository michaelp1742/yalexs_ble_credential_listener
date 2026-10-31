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

from custom_components.yalexs_ble_credential_listener.const import (
    CONF_ATTRIBUTION,
    CONF_LOCK_MODEL,
    DOMAIN,
    OWNER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant

from . import ADDRESS, TITLE


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
def has_seam() -> bool:
    """Return whether core's yalexs_ble has the attribution seam."""
    return True


@pytest.fixture
def seam() -> Mock:
    """Return a stand-in for the helpers module of core's yalexs_ble."""
    return Mock(spec_set=["async_register_attributor"])


@pytest.fixture(autouse=True)
def mock_owner_integration(
    hass: HomeAssistant, has_seam: bool, seam: Mock
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
    if has_seam:
        mock_platform(hass, f"{OWNER_DOMAIN}.helpers", seam)
    with mock_config_flow(OWNER_DOMAIN, _OwnerConfigFlow):
        yield


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
