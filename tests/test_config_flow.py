"""Tests for the Yale Access Bluetooth Credential Listener config flow."""

from typing import Any

from freezegun.api import FrozenDateTimeFactory
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from yalexs_ble import LockStatus

from custom_components.yalexs_ble_credential_listener.attribution import LockAttributor
from custom_components.yalexs_ble_credential_listener.const import (
    CONF_ATTRIBUTION,
    CONF_LOCK_MODEL,
    DOMAIN,
    OWNER_DOMAIN,
)
from custom_components.yalexs_ble_credential_listener.models import LOCK_MODELS
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import (
    ADDRESS,
    CODE_SLOT_FFEE_UNLOCKED,
    FRONT_ADDRESS,
    FRONT_TITLE,
    TITLE,
    async_advance,
    async_deliver,
    async_setup_owner,
    lock_status_change,
)

LOCK_MODEL_OPTIONS = [
    {"value": model.key, "label": model.name} for model in LOCK_MODELS
]


def _listed_locks(result: dict[str, Any]) -> list[dict[str, str]]:
    """Return the locks the form offers."""
    return result["data_schema"].schema[CONF_ADDRESS].config["options"]


async def test_user_flow_adds_each_loaded_lock_once_with_its_model(
    hass: HomeAssistant,
) -> None:
    """Each loaded lock gets one entry with the model picked, and none left aborts."""
    await async_setup_owner(hass)
    await async_setup_owner(hass, FRONT_ADDRESS, FRONT_TITLE)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert _listed_locks(result) == [
        {"value": ADDRESS, "label": TITLE},
        {"value": FRONT_ADDRESS, "label": FRONT_TITLE},
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: ADDRESS}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "model"
    (field,) = result["data_schema"].schema
    assert field.default is probatio.UNDEFINED
    selector = result["data_schema"].schema[field]
    assert selector.config["options"] == LOCK_MODEL_OPTIONS
    assert selector.config["mode"] == "dropdown"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCK_MODEL: "unity"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {CONF_ADDRESS: ADDRESS}
    assert result["options"] == {CONF_ATTRIBUTION: False, CONF_LOCK_MODEL: "unity"}
    assert result["result"].unique_id == ADDRESS

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert _listed_locks(result) == [{"value": FRONT_ADDRESS, "label": FRONT_TITLE}]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ADDRESS: FRONT_ADDRESS}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCK_MODEL: "other"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"


async def test_user_flow_lists_only_loaded_locks(hass: HomeAssistant) -> None:
    """A lock whose entry of core's yalexs_ble is not loaded is not listed."""
    await async_setup_owner(hass)
    MockConfigEntry(
        domain=OWNER_DOMAIN,
        title=FRONT_TITLE,
        data={CONF_ADDRESS: FRONT_ADDRESS},
        unique_id=FRONT_ADDRESS,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert _listed_locks(result) == [{"value": ADDRESS, "label": TITLE}]


@pytest.mark.parametrize(
    ("first_inputs", "reason"),
    [
        pytest.param(
            [{CONF_ADDRESS: ADDRESS}, {CONF_LOCK_MODEL: "unity"}],
            "already_configured",
            id="entry added",
        ),
        pytest.param(
            [{CONF_ADDRESS: ADDRESS}], "already_in_progress", id="at the model"
        ),
    ],
)
async def test_user_flow_aborts_for_a_lock_another_flow_took(
    hass: HomeAssistant, first_inputs: list[dict[str, str]], reason: str
) -> None:
    """A flow submitted after another flow took the lock aborts."""
    await async_setup_owner(hass)
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    for user_input in first_inputs:
        await hass.config_entries.flow.async_configure(first["flow_id"], user_input)

    result = await hass.config_entries.flow.async_configure(
        second["flow_id"], {CONF_ADDRESS: ADDRESS}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.parametrize("has_hook", [False])
async def test_user_flow_aborts_without_the_attribution_hook(
    hass: HomeAssistant,
) -> None:
    """The user step aborts when core's yalexs_ble has no attribution hook."""
    await async_setup_owner(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_attribution_hook"


async def test_options_flow_changes_the_lock_model(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    config_entry: MockConfigEntry,
) -> None:
    """A new lock model from the options flow reloads the entry, which names slots by it."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    attribution_field, lock_model_field = result["data_schema"].schema
    assert attribution_field.default() is True
    assert lock_model_field.default() == "unity"
    selector = result["data_schema"].schema[lock_model_field]
    assert selector.config["options"] == LOCK_MODEL_OPTIONS
    assert selector.config["mode"] == "dropdown"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_ATTRIBUTION: True, CONF_LOCK_MODEL: "doorman_classic"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_ATTRIBUTION: True,
        CONF_LOCK_MODEL: "doorman_classic",
    }
    assert config_entry.state is ConfigEntryState.LOADED
    reloaded = config_entry.runtime_data
    assert isinstance(reloaded, LockAttributor)
    assert reloaded is not attributor
    change = lock_status_change(LockStatus.UNLOCKED)
    reloaded.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, CODE_SLOT_FFEE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)
    assert [changed_by for changed_by, _ in change.sets] == ["Keypad slot 65518"]
