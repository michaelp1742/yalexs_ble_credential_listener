"""The Yale Access Bluetooth Credential Listener integration."""

from types import ModuleType
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .const import OWNER_DOMAIN

if TYPE_CHECKING:
    from homeassistant.components.yalexs_ble import YALEXSBLEConfigEntry

type YaleXSBLECredentialListenerConfigEntry = ConfigEntry[None]


@callback
def async_loaded_owners(hass: HomeAssistant) -> dict[str, YALEXSBLEConfigEntry]:
    """Return the loaded entries of core's yalexs_ble by lock address."""
    return {
        owner.data[CONF_ADDRESS]: owner
        for owner in hass.config_entries.async_loaded_entries(OWNER_DOMAIN)
    }


async def async_seam(hass: HomeAssistant) -> ModuleType | None:
    """Return the helpers module of the yalexs_ble that is loaded, or None if it has none."""
    integration = await async_get_integration(hass, OWNER_DOMAIN)
    try:
        # A direct import of homeassistant.components.yalexs_ble.helpers would load
        # the release's stock yalexs_ble when the loaded one is an override from
        # custom_components; the loader imports from the package that is loaded.
        return await integration.async_get_platform("helpers")
    except ImportError as err:
        # err.name is the module whose import failed, so only an absent helpers
        # module returns None. A helpers module that fails its own imports is a
        # broken install, and its error propagates.
        if err.name != f"{integration.pkg_path}.helpers":
            raise
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: YaleXSBLECredentialListenerConfigEntry
) -> bool:
    """Set up the entry, which runs nothing for the lock."""
    entry.runtime_data = None
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YaleXSBLECredentialListenerConfigEntry
) -> bool:
    """Unload a config entry."""
    return True
