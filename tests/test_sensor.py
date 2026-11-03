"""Tests for the Yale Access Bluetooth Credential Listener attribution time sensors."""

from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator
from yalexs_ble import LockStatus

from custom_components.yalexs_ble_credential_listener.attribution import LockAttributor
from custom_components.yalexs_ble_credential_listener.const import (
    CONF_ATTRIBUTION,
    CONF_LOCK_MODEL,
)
from homeassistant.components.config import device_registry as config_device_registry
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from . import (
    ADDRESS,
    CODE_SLOT_1_UNLOCKED,
    MAXIMUM,
    MEDIAN,
    REMOTE_UNLOCKED,
    TITLE,
    async_advance,
    async_deliver,
    lock_status_change,
)


async def _async_set_after(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner: MockConfigEntry,
    attributor: LockAttributor,
    seconds: float,
) -> None:
    """Tell the attributor of a change, and have its cause set seconds after the change."""
    attributor.async_lock_status_changed(lock_status_change(LockStatus.UNLOCKED))
    await async_advance(hass, freezer, seconds - 0.75)
    await async_deliver(owner, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)


@pytest.mark.parametrize("attribution", [False])
async def test_option_on_adds_the_sensors_on_a_linked_device(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    hass_ws_client: WebSocketGenerator,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    core_lock: er.RegistryEntry,
    config_entry: MockConfigEntry,
) -> None:
    """Turning the option on adds both sensors, unknown, on a device linked to core's."""
    # Unloading a platform never forwarded logs "Ignored unload request" only
    # while the sensor component is loaded, and core's yalexs_ble entries load it.
    assert await async_setup_component(hass, "sensor", {})
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ATTRIBUTION: True, CONF_LOCK_MODEL: "unity"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.state is ConfigEntryState.LOADED
    assert "Ignored unload request" not in caplog.text
    devices = set()
    for entity_id, key in (
        (MEDIAN, "attribution_time_median"),
        (MAXIMUM, "attribution_time_maximum"),
    ):
        entity = entity_registry.async_get(entity_id)
        assert entity is not None
        assert entity.unique_id == f"{ADDRESS}_{key}"
        assert entity.entity_category is EntityCategory.DIAGNOSTIC
        assert entity.options["sensor"]["suggested_display_precision"] == 2
        state = hass.states.get(entity_id)
        assert state.state == STATE_UNKNOWN
        assert state.attributes["device_class"] == SensorDeviceClass.DURATION
        assert state.attributes["unit_of_measurement"] == UnitOfTime.SECONDS
        assert state.attributes["samples"] == 0
        devices.add(entity.device_id)
    (device_id,) = devices
    device = device_registry.async_get(device_id)
    assert device is not None
    assert device.config_entry_id == config_entry.entry_id
    assert device.connections == {(dr.CONNECTION_BLUETOOTH, ADDRESS)}
    assert device.name == TITLE

    config_device_registry.async_setup(hass)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "config/device_registry/list_linked_devices",
            "device_id": core_lock.device_id,
        }
    )
    msg = await client.receive_json()
    assert msg["result"]["linked_devices"] == [device.id]


async def test_sensors_show_the_median_and_maximum_of_the_times(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """The sensors show the median and the maximum of every time since the entry loaded."""
    for seconds in (1.35, 2.8, 2.0):
        await _async_set_after(hass, freezer, owner_entry, attributor, seconds)

    median = hass.states.get(MEDIAN)
    maximum = hass.states.get(MAXIMUM)
    assert float(median.state) == pytest.approx(2.0)
    assert float(maximum.state) == pytest.approx(2.8)
    assert median.attributes["samples"] == maximum.attributes["samples"] == 3


async def test_the_sensors_keep_the_last_1000_times(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """The 1001st time drops the oldest."""
    await _async_set_after(hass, freezer, owner_entry, attributor, 3.0)
    for _ in range(1000):
        await _async_set_after(hass, freezer, owner_entry, attributor, 1.35)

    maximum = hass.states.get(MAXIMUM)
    assert float(maximum.state) == pytest.approx(1.35)
    assert maximum.attributes["samples"] == 1000


async def test_a_reload_starts_the_sensors_afresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    config_entry: MockConfigEntry,
) -> None:
    """After a reload of the entry both sensors are unknown with no samples."""
    attributor.async_lock_status_changed(lock_status_change(LockStatus.UNLOCKED))
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED)
    await async_advance(hass, freezer, 0.75)
    assert hass.states.get(MEDIAN).attributes["samples"] == 1

    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    for entity_id in (MEDIAN, MAXIMUM):
        state = hass.states.get(entity_id)
        assert state.state == STATE_UNKNOWN
        assert state.attributes["samples"] == 0


async def test_option_off_removes_the_reader_and_leaves_the_sensors_unavailable(
    hass: HomeAssistant,
    hook: Mock,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    config_entry: MockConfigEntry,
) -> None:
    """Turning the option off removes the registrations and leaves both sensors unavailable."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ATTRIBUTION: False, CONF_LOCK_MODEL: "unity"}
    )
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is None
    owner_entry.runtime_data.lock.register_log_record_callback.return_value.assert_called_once()
    hook.async_register_attributor.return_value.assert_called_once()
    for entity_id in (MEDIAN, MAXIMUM):
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
