"""Config flow for the Yale Access Bluetooth Credential Listener integration."""

from typing import Any, override

import probatio

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import async_loaded_owners, async_seam
from .const import CONF_ATTRIBUTION, CONF_LOCK_MODEL, DOMAIN
from .models import LOCK_MODELS

LOCK_MODEL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            SelectOptionDict(value=model.key, label=model.name) for model in LOCK_MODELS
        ],
        mode=SelectSelectorMode.DROPDOWN,
    )
)


class YaleXSBLECredentialListenerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yale Access Bluetooth Credential Listener."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._titles: dict[str, str] = {}
        self._address = ""

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick a lock that core's yalexs_ble has loaded."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            return await self.async_step_model()

        if await async_seam(self.hass) is None:
            return self.async_abort(reason="no_attribution_seam")
        current_addresses = self._async_current_ids()
        self._titles = {
            address: owner.title
            for address, owner in async_loaded_owners(self.hass).items()
            if address not in current_addresses
        }
        if not self._titles:
            return self.async_abort(reason="no_locks")

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_ADDRESS): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=address, label=title)
                                for address, title in self._titles.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the step to pick the lock's model."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._titles[self._address],
                data={CONF_ADDRESS: self._address},
                options={
                    CONF_ATTRIBUTION: False,
                    CONF_LOCK_MODEL: user_input[CONF_LOCK_MODEL],
                },
            )

        return self.async_show_form(
            step_id="model",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_LOCK_MODEL): LOCK_MODEL_SELECTOR}
            ),
        )
