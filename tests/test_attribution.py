"""Tests for the Yale Access Bluetooth Credential Listener attribution."""

from collections.abc import Callable
import time
from unittest.mock import Mock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from yalexs_ble import LockStatus, parse_log_event_packet

from custom_components.yalexs_ble_credential_listener.attribution import (
    LockAttributor,
    attribution_for,
)
from custom_components.yalexs_ble_credential_listener.const import (
    ACTIVITY_WINDOW_SECONDS,
    EVENT_LOCK_ACTIVITY,
)
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import (
    AUTO_RELOCK_LOCKED,
    BLUETOOTH_RECEIVED_LOCKED,
    CODE_SLOT_1_UNLOCKED,
    CODE_SLOT_FFEE_UNLOCKED,
    END_OF_LOG,
    FINGER_SLOT_8_UNLOCKED,
    INSIDE_BUTTON_LOCKED,
    INSIDE_DOOR_PIN_SLOT_FFEE_UNLOCKED,
    KEYPAD_BUTTON_LOCKED,
    KEYPAD_INFO,
    LOCK,
    MANUAL_UNLOCKED,
    MAXIMUM,
    MEDIAN,
    ONE_TOUCH_LOCKED,
    PIN_SLOT_3_ERROR,
    PIN_SLOT_3_UNLOCKED,
    REMOTE_SECUREMODE,
    REMOTE_UNLOCKED,
    RF_SLOT_7_UNLOCKED,
    RF_SLOT_8_ERROR,
    SECURE_MODE_LOCK,
    UNITY,
    LockStatusChangeDouble,
    async_advance,
    async_deliver,
    lock_state,
    lock_status_change,
    sensor_reading,
)


@pytest.mark.parametrize(
    ("code_at", "set_at"),
    [
        pytest.param(1.25, 2.0, id="code on the next read"),
        pytest.param(2.05, 2.8, id="a status poll between the reads"),
    ],
)
async def test_a_keypad_code_sets_changed_by_with_its_slot(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    core_lock: er.RegistryEntry,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    code_at: float,
    set_at: float,
) -> None:
    """A CodeOperation after the KeypadInfo fires the event and then sets changed_by when the settle timer ends."""
    change = lock_status_change(LockStatus.UNLOCKED)
    fired: list[tuple[Event, list[tuple[str, Context | None]]]] = []

    @callback
    def _async_keep_event(event: Event) -> None:
        """Keep the event with the sets made on the change before it."""
        fired.append((event, list(change.sets)))

    hass.bus.async_listen(EVENT_LOCK_ACTIVITY, _async_keep_event)
    changed_at = time.time()

    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, KEYPAD_INFO)
    await async_advance(hass, freezer, code_at - 0.6)
    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED)
    await async_advance(hass, freezer, set_at - code_at - 0.01)
    assert change.sets == []
    await async_advance(hass, freezer, 0.01)

    ((changed_by, context),) = change.sets
    assert changed_by == "Keypad slot 1"
    assert isinstance(context, Context)
    ((event, sets_before_event),) = fired
    assert sets_before_event == []
    assert event.context is context
    assert event.time_fired_timestamp == changed_at
    assert event.data == {
        "device_id": core_lock.device_id,
        "entity_id": LOCK,
        "source": "pin",
        "slot": 1,
        "master_code": False,
        "changed_by": "Keypad slot 1",
    }
    for entity_id in (MEDIAN, MAXIMUM):
        assert sensor_reading(hass, entity_id) == (pytest.approx(set_at), 1)


@pytest.mark.parametrize(
    ("lock_model", "status", "record", "changed_by", "source", "slot", "master_code"),
    [
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            CODE_SLOT_FFEE_UNLOCKED,
            "Master code",
            "pin",
            None,
            True,
            id="master code",
        ),
        pytest.param(
            "doorman_classic",
            LockStatus.UNLOCKED,
            CODE_SLOT_FFEE_UNLOCKED,
            "Keypad slot 65518",
            "pin",
            0xFFEE,
            False,
            id="no master code slot for the model",
        ),
        pytest.param(
            "retired",
            LockStatus.UNLOCKED,
            CODE_SLOT_FFEE_UNLOCKED,
            "Keypad slot 65518",
            "pin",
            0xFFEE,
            False,
            id="a stored key no row has takes the other row",
        ),
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            PIN_SLOT_3_UNLOCKED,
            "Keypad slot 3",
            "pin",
            3,
            False,
            id="PIN credential",
        ),
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            INSIDE_DOOR_PIN_SLOT_FFEE_UNLOCKED,
            "Master code",
            "pin",
            None,
            True,
            id="inside door PIN credential at the master code slot",
        ),
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            RF_SLOT_7_UNLOCKED,
            "RF tag slot 7",
            "rf",
            7,
            False,
            id="RF tag",
        ),
        pytest.param(
            "unity",
            LockStatus.LOCKED,
            AUTO_RELOCK_LOCKED,
            "Auto lock",
            "auto_lock",
            None,
            False,
            id="auto relock",
        ),
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            REMOTE_UNLOCKED,
            "Remote",
            "remote",
            None,
            False,
            id="BLE command",
        ),
        pytest.param(
            "unity",
            LockStatus.LOCKED,
            KEYPAD_BUTTON_LOCKED,
            "Keypad",
            "pin",
            None,
            False,
            id="keypad button",
        ),
        pytest.param(
            "unity",
            LockStatus.LOCKED,
            ONE_TOUCH_LOCKED,
            "Keypad",
            "pin",
            None,
            False,
            id="one touch",
        ),
        pytest.param(
            "unity",
            LockStatus.LOCKED,
            INSIDE_BUTTON_LOCKED,
            "Manual",
            "manual",
            None,
            False,
            id="inside button",
        ),
        pytest.param(
            "unity",
            LockStatus.UNLOCKED,
            MANUAL_UNLOCKED,
            "Manual",
            "manual",
            None,
            False,
            id="manual",
        ),
        pytest.param(
            "unity",
            LockStatus.SECUREMODE,
            AUTO_RELOCK_LOCKED,
            "Auto lock",
            "auto_lock",
            None,
            False,
            id="secure mode matched as locked",
        ),
        pytest.param(
            "unity",
            LockStatus.SECUREMODE,
            REMOTE_SECUREMODE,
            "Remote",
            "remote",
            None,
            False,
            id="a secure mode record matched as locked",
        ),
    ],
)
async def test_a_claimed_record_names_the_cause(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    status: LockStatus,
    record: bytes,
    changed_by: str,
    source: str,
    slot: int | None,
    master_code: bool,
) -> None:
    """Each claimed record sets its words on the change and fires its event."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(status)

    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, record)
    await async_advance(hass, freezer, 0.75)

    ((set_by, context),) = change.sets
    assert set_by == changed_by
    (event,) = events
    assert event.context is context
    assert event.data["source"] == source
    assert event.data["slot"] == slot
    assert event.data["master_code"] is master_code
    assert event.data["changed_by"] == changed_by


async def test_a_commanded_change_is_not_matched(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """A change Home Assistant commanded is set no cause by its own record."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED, commanded=True)

    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)

    assert change.sets == []
    assert events == []


async def test_a_record_after_the_set_sets_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """A claimed record of the change's status after its cause was set sets nothing and fires no event."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)
    assert [changed_by for changed_by, _ in change.sets] == ["Remote"]

    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)

    assert [changed_by for changed_by, _ in change.sets] == ["Remote"]
    assert len(events) == 1
    assert sensor_reading(hass, MAXIMUM) == (pytest.approx(1.35), 1)


async def test_each_lock_entity_is_set_with_one_context(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """Each lock entity's change for one report is set under one context, with one event and one time."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    new_state = lock_state(LockStatus.LOCKED)
    change = LockStatusChangeDouble(LOCK, new_state)
    secure_change = LockStatusChangeDouble(SECURE_MODE_LOCK, new_state)
    changed_at = time.time()

    attributor.async_lock_status_changed(change)
    attributor.async_lock_status_changed(secure_change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, AUTO_RELOCK_LOCKED)
    await async_advance(hass, freezer, 0.75)

    ((changed_by, context),) = change.sets
    assert changed_by == "Auto lock"
    assert secure_change.sets == [("Auto lock", context)]
    (event,) = events
    assert event.context is context
    assert event.time_fired_timestamp == changed_at
    assert sensor_reading(hass, MAXIMUM) == (pytest.approx(1.35), 1)


def _same_report(first: LockStatusChangeDouble) -> Mock:
    """Return the new_state of first, as the library passes it to the other entity."""
    return first.new_state


def _new_report(first: LockStatusChangeDouble) -> Mock:
    """Return a new lock state of first's status, as the library builds for a new report."""
    return lock_state(first.new_state.lock)


@pytest.mark.parametrize(
    ("second_entity_id", "new_state_of", "first_sets", "started_after", "maximum"),
    [
        pytest.param(
            SECURE_MODE_LOCK,
            _same_report,
            ["Remote"],
            0.0,
            1.05,
            id="the other entity's report of the change",
        ),
        pytest.param(
            LOCK,
            _new_report,
            [],
            0.5,
            1.3,
            id="a new report of the same status",
        ),
    ],
)
async def test_only_a_new_report_starts_a_new_change(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    second_entity_id: str,
    new_state_of: Callable[[LockStatusChangeDouble], Mock],
    first_sets: list[str],
    started_after: float,
    maximum: float,
) -> None:
    """A report with the latest change's new_state keeps its candidate and its time, and a new report drops them."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    first = lock_status_change(LockStatus.UNLOCKED)
    changed_at = time.time()
    attributor.async_lock_status_changed(first)
    await async_advance(hass, freezer, 0.3)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.2)
    second = LockStatusChangeDouble(second_entity_id, new_state_of(first))

    attributor.async_lock_status_changed(second)
    await async_advance(hass, freezer, 0.55)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)

    assert [changed_by for changed_by, _ in first.sets] == first_sets
    (event,) = events
    assert second.sets == [("Remote", event.context)]
    assert event.time_fired_timestamp == pytest.approx(changed_at + started_after)
    assert sensor_reading(hass, MAXIMUM) == (pytest.approx(maximum), 1)


@pytest.mark.parametrize(
    ("first", "record", "later", "commanded", "follow_up"),
    [
        pytest.param(
            LockStatus.UNLOCKED,
            REMOTE_UNLOCKED,
            LockStatus.LOCKED,
            False,
            REMOTE_UNLOCKED,
            id="another status",
        ),
        pytest.param(
            LockStatus.LOCKED,
            INSIDE_BUTTON_LOCKED,
            LockStatus.SECUREMODE,
            False,
            KEYPAD_INFO,
            id="a status matched as the same",
        ),
        pytest.param(
            LockStatus.LOCKED,
            INSIDE_BUTTON_LOCKED,
            LockStatus.SECUREMODE,
            True,
            REMOTE_SECUREMODE,
            id="a commanded change and its own record",
        ),
        pytest.param(
            LockStatus.UNLOCKED,
            REMOTE_UNLOCKED,
            LockStatus.UNLOCKING,
            False,
            REMOTE_UNLOCKED,
            id="a transitional status",
        ),
    ],
)
async def test_the_next_change_ends_the_matching_of_the_one_before(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    first: LockStatus,
    record: bytes,
    later: LockStatus,
    commanded: bool,
    follow_up: bytes,
) -> None:
    """The next change drops the candidate of the change before it, so no record names that change."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    earlier = lock_status_change(first)
    attributor.async_lock_status_changed(earlier)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, record)
    await async_advance(hass, freezer, 0.4)
    # Core starts writing the next change before it tells the attributor of it.
    earlier.latest = False
    next_change = lock_status_change(later, commanded=commanded)

    attributor.async_lock_status_changed(next_change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, follow_up)
    await async_advance(hass, freezer, 0.75)

    assert earlier.sets == []
    assert next_change.sets == []
    assert events == []


async def test_a_later_claimed_record_replaces_the_candidate(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """A later claimed record of the change's status replaces the candidate and restarts the settle timer."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.LOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, INSIDE_BUTTON_LOCKED)
    await async_advance(hass, freezer, 0.4)

    await async_deliver(owner_entry, AUTO_RELOCK_LOCKED)
    await async_advance(hass, freezer, 0.74)
    assert change.sets == []
    await async_advance(hass, freezer, 0.01)

    assert [changed_by for changed_by, _ in change.sets] == ["Auto lock"]
    (event,) = events
    assert event.data["changed_by"] == "Auto lock"


@pytest.mark.parametrize(
    ("record", "set_at"),
    [
        pytest.param(END_OF_LOG, 2.0, id="GetLogError"),
        pytest.param(KEYPAD_INFO, 2.55, id="unclaimed record"),
        pytest.param(AUTO_RELOCK_LOCKED, 2.55, id="claimed record of another status"),
    ],
)
async def test_records_after_the_candidate_restart_the_settle_timer_unless_get_log_error(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    record: bytes,
    set_at: float,
) -> None:
    """A record that does not replace the candidate restarts the settle timer, and a GetLogError does not."""
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, record)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, record)
    await async_advance(hass, freezer, 0.05)
    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED)
    await async_advance(hass, freezer, 0.55)
    await async_deliver(owner_entry, record)

    await async_advance(hass, freezer, set_at - 1.8 - 0.01)
    assert change.sets == []
    await async_advance(hass, freezer, 0.01)

    assert [changed_by for changed_by, _ in change.sets] == ["Keypad slot 1"]


async def test_a_backlog_record_is_not_matched(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """A record delivered with backlog True is not matched to the change."""
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)

    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED, backlog=True)
    await async_advance(hass, freezer, 0.75)
    assert change.sets == []
    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED)
    await async_advance(hass, freezer, 0.75)

    assert [changed_by for changed_by, _ in change.sets] == ["Keypad slot 1"]


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(RF_SLOT_8_ERROR, id="credential error"),
        pytest.param(FINGER_SLOT_8_UNLOCKED, id="fingerprint credential"),
        pytest.param(BLUETOOTH_RECEIVED_LOCKED, id="op code not claimed"),
        pytest.param(END_OF_LOG, id="the app read the record first"),
    ],
)
async def test_a_change_with_no_claimed_record_keeps_no_cause(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    record: bytes,
) -> None:
    """A change whose records the listener does not claim is set no cause, with no event and no time."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)

    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, record)
    await async_advance(hass, freezer, ACTIVITY_WINDOW_SECONDS)

    assert change.sets == []
    assert events == []
    assert sensor_reading(hass, MAXIMUM) == (None, 0)


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(PIN_SLOT_3_ERROR, id="PIN"),
        pytest.param(RF_SLOT_8_ERROR, id="RF tag"),
    ],
)
def test_a_credential_record_with_an_error_is_not_claimed(record: bytes) -> None:
    """attribution_for claims no CredentialOperation that holds a credential error."""
    assert attribution_for(parse_log_event_packet(record), UNITY) is None


@pytest.mark.parametrize(
    ("record_at", "sets", "reading"),
    [
        pytest.param(6.0, ["Remote"], (6.75, 1), id="inside the window"),
        pytest.param(
            9.2, ["Remote"], (9.95, 1), id="a settle timer ending inside the window"
        ),
        pytest.param(10.1, [], (None, 0), id="past the window"),
    ],
)
async def test_a_record_names_the_change_only_inside_the_window(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    record_at: float,
    sets: list[str],
    reading: tuple[float | None, int],
) -> None:
    """A claimed record sets the change's cause, with the event, only within ACTIVITY_WINDOW_SECONDS of the change."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, record_at)

    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    await async_advance(hass, freezer, 0.75)

    assert [changed_by for changed_by, _ in change.sets] == sets
    assert len(events) == len(sets)
    value, samples = reading
    assert sensor_reading(hass, MAXIMUM) == (pytest.approx(value), samples)


@pytest.mark.parametrize(
    "records",
    [
        pytest.param(19, id="a record past the window"),
        pytest.param(18, id="the settle timer ending past the window"),
    ],
)
async def test_a_candidate_past_the_window_is_dropped(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
    records: int,
) -> None:
    """A candidate whose cause is still unset ACTIVITY_WINDOW_SECONDS after the change is dropped with no event and no time."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, CODE_SLOT_1_UNLOCKED)

    # Unclaimed records every 0.5 s keep restarting the settle timer. The last
    # arrives at 10.1 s, past the window, or at 9.6 s, so the timer it restarts
    # ends at 10.35 s, past the window.
    for _ in range(records):
        await async_advance(hass, freezer, 0.5)
        await async_deliver(owner_entry, KEYPAD_INFO)
    await async_advance(hass, freezer, 0.75)

    assert change.sets == []
    assert events == []
    assert sensor_reading(hass, MAXIMUM) == (None, 0)


async def test_a_set_on_a_change_core_no_longer_shows_fires_no_event(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    owner_entry: MockConfigEntry,
    attributor: LockAttributor,
) -> None:
    """A change that is no longer latest when the settle timer ends is still set, with no event and no time."""
    events = async_capture_events(hass, EVENT_LOCK_ACTIVITY)
    change = lock_status_change(LockStatus.UNLOCKED)
    attributor.async_lock_status_changed(change)
    await async_advance(hass, freezer, 0.6)
    await async_deliver(owner_entry, REMOTE_UNLOCKED)
    # The lock entity has started writing its next change, of which the attributor
    # has not been told.
    change.latest = False

    await async_advance(hass, freezer, 0.75)

    assert [changed_by for changed_by, _ in change.sets] == ["Remote"]
    assert events == []
    assert sensor_reading(hass, MAXIMUM) == (None, 0)
