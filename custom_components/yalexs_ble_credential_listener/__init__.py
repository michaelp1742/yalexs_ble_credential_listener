"""The Yale Access Bluetooth Credential Listener integration."""

import logging
from types import ModuleType
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.loader import async_get_integration

from .attribution import LockAttributor
from .const import CONF_ATTRIBUTION, CONF_LOCK_MODEL, DOMAIN, OWNER_DOMAIN
from .models import LOCK_MODELS

if TYPE_CHECKING:
    from homeassistant.components.yalexs_ble import YALEXSBLEConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type YaleXSBLECredentialListenerConfigEntry = ConfigEntry[LockAttributor | None]


@callback
def async_loaded_owners(hass: HomeAssistant) -> dict[str, YALEXSBLEConfigEntry]:
    """Return the loaded entries of core's yalexs_ble by lock address."""
    return {
        owner.data[CONF_ADDRESS]: owner
        for owner in hass.config_entries.async_loaded_entries(OWNER_DOMAIN)
    }


async def async_hook(hass: HomeAssistant) -> ModuleType | None:
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
    """Set up the entry, which runs nothing while its option is off."""
    if not entry.options[CONF_ATTRIBUTION]:
        entry.runtime_data = None
        return True
    address = entry.data[CONF_ADDRESS]
    if (owner := async_loaded_owners(hass).get(address)) is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="owner_not_loaded"
        )
    if (hook := await async_hook(hass)) is None:
        _LOGGER.warning(
            "The loaded Yale Access Bluetooth integration has no helpers module "
            "with async_register_attributor, so %s attributes no lock change",
            entry.title,
        )
        entry.runtime_data = None
        return True
    models = {model.key: model for model in LOCK_MODELS}
    # A stored key that no row has, such as one a later release removed, takes the
    # row for any other lock.
    model = models.get(entry.options[CONF_LOCK_MODEL], models["other"])
    attributor = entry.runtime_data = LockAttributor(hass, address, model)

    reload_scheduled = False

    @callback
    def _async_owner_changed() -> None:
        """Schedule one reload of this entry when core's entry changes state."""
        nonlocal reload_scheduled
        if reload_scheduled:
            return
        reload_scheduled = True
        # A reload started inside the listener loop of core's entry can remove this
        # listener while the loop runs, and the loop then skips the listener after it.
        hass.loop.call_soon(hass.config_entries.async_schedule_reload, entry.entry_id)

    entry.async_on_unload(owner.async_on_state_change(_async_owner_changed))
    entry.async_on_unload(
        owner.runtime_data.lock.register_log_record_callback(
            attributor.async_log_record
        )
    )
    entry.async_on_unload(hook.async_register_attributor(hass, address, attributor))
    entry.async_on_unload(attributor.async_cancel)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YaleXSBLECredentialListenerConfigEntry
) -> bool:
    """Unload a config entry."""
    if entry.runtime_data is None:
        # Setup forwarded no platform. The option is not checked here: the options
        # flow stores its new value before the reload that runs this unload.
        return True
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
