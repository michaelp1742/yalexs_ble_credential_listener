"""Attribute lock changes from the lock's activity log records."""

from collections import deque
from collections.abc import Sequence
from datetime import datetime
from functools import partial
import time
from typing import TYPE_CHECKING, NamedTuple

from yalexs_ble import (
    CodeOperation,
    CredentialOperation,
    GetLogError,
    LockCred,
    LockOperation,
    LockStatus,
    LogRecord,
    OpCode,
    parse_log_event_packet,
)

from homeassistant.components.lock import ATTR_CHANGED_BY, DOMAIN as LOCK_DOMAIN
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from .const import (
    ACTIVITY_SETTLE_SECONDS,
    ACTIVITY_WINDOW_SECONDS,
    ATTR_MASTER_CODE,
    ATTR_SLOT,
    ATTR_SOURCE,
    EVENT_LOCK_ACTIVITY,
    OWNER_DOMAIN,
    SOURCE_AUTO_LOCK,
    SOURCE_MANUAL,
    SOURCE_PIN,
    SOURCE_REMOTE,
    SOURCE_RF,
)
from .models import LockModel

if TYPE_CHECKING:
    from homeassistant.components.yalexs_ble.helpers import LockStatusChange

MATCH_STATUS: dict[LockStatus, LockStatus] = {
    LockStatus.LOCKED: LockStatus.LOCKED,
    LockStatus.SECUREMODE: LockStatus.LOCKED,
    LockStatus.UNLOCKED: LockStatus.UNLOCKED,
}

TIMES_KEPT = 1000


class Attribution(NamedTuple):
    """The cause of a lock change that a record names."""

    changed_by: str
    source: str
    slot: int | None
    master_code: bool


def attribution_for(record: LogRecord, model: LockModel) -> Attribution | None:
    """Return the cause a record names, or None for a record that is not claimed."""
    match record:
        case (
            CodeOperation(slot=slot)
            | CredentialOperation(
                credential_type=LockCred.PIN | LockCred.INSIDE_DOOR_PIN,
                credential_error=None,
                slot=slot,
            )
        ):
            if slot == model.master_code_slot:
                return Attribution("Master code", SOURCE_PIN, None, True)
            return Attribution(f"Keypad slot {slot}", SOURCE_PIN, slot, False)
        case CredentialOperation(
            credential_type=LockCred.RF, credential_error=None, slot=slot
        ):
            return Attribution(f"RF tag slot {slot}", SOURCE_RF, slot, False)
        # In field captures a press of the keypad's Yale button was recorded as
        # DOOR_STATE_CHANGED with key_slot 0xFF, and a command over Bluetooth with
        # key_slot 0.
        case (
            LockOperation(op_code=OpCode.DOOR_STATE_CHANGED, key_slot=0xFF)
            | LockOperation(op_code=OpCode.ONE_TOUCH)
        ):
            return Attribution("Keypad", SOURCE_PIN, None, False)
        case LockOperation(op_code=OpCode.DOOR_STATE_CHANGED):
            return Attribution("Remote", SOURCE_REMOTE, None, False)
        case LockOperation(
            op_code=OpCode.DOOR_MANUAL_STATE_CHANGE | OpCode.INSIDE_BUTTON
        ):
            return Attribution("Manual", SOURCE_MANUAL, None, False)
        case LockOperation(op_code=OpCode.AUTO_RELOCK):
            return Attribution("Auto lock", SOURCE_AUTO_LOCK, None, False)
    return None


class LockAttributor:
    """Set changed_by on each change of one lock's status to the cause a record names."""

    def __init__(self, hass: HomeAssistant, address: str, model: LockModel) -> None:
        """Initialize the attributor for the lock at address."""
        self._hass = hass
        self._address = address
        self._model = model
        self._changes: list[LockStatusChange] = []
        self._change_started = 0.0
        self._change_started_monotonic = 0.0
        self._times: deque[float] = deque(maxlen=TIMES_KEPT)
        self._time_listeners: list[CALLBACK_TYPE] = []
        self._candidate: Attribution | None = None
        self._settle_cancel: CALLBACK_TYPE | None = None
        self._entity_id: str | None = None
        self._device_id: str | None = None

    @property
    def times(self) -> Sequence[float]:
        """Return the times from a lock change to the set of its cause."""
        return self._times

    @callback
    def async_add_time_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call listener after each time added, and return its remover."""
        self._time_listeners.append(listener)
        return partial(self._time_listeners.remove, listener)

    @callback
    def async_lock_status_changed(self, change: LockStatusChange) -> None:
        """Take a change of the lock status that a lock entity has written."""
        if change.commanded or change.new_state.lock not in MATCH_STATUS:
            # The lock entity has written this change over the one before it, and
            # core applies no set on a change that is no longer latest.
            self._async_end_matching()
            return
        # The library passes one LockState to every lock entity for one report, so
        # the other entity's report of a change is not a new change.
        if not self._changes or change.new_state is not self._changes[-1].new_state:
            self._async_end_matching()
            self._change_started = time.time()
            self._change_started_monotonic = time.monotonic()
        self._changes.append(change)
        if self._entity_id is None:
            registry = er.async_get(self._hass)
            self._entity_id = registry.async_get_entity_id(
                LOCK_DOMAIN, OWNER_DOMAIN, self._address
            )
            lock = registry.async_get(self._entity_id) if self._entity_id else None
            self._device_id = lock.device_id if lock else None

    async def async_log_record(self, raw: bytes, backlog: bool) -> None:
        """Match an activity log record to the change of the lock status it names."""
        if backlog:
            # A backlog record was unread on the lock when the first drain after the
            # reader's registration began, so it can name a change made before this
            # attributor was registered.
            return
        record = parse_log_event_packet(raw)
        match record:
            case GetLogError():
                # The drain reads on past the log's end for its window, and the lock
                # answers each of those reads with a GetLogError, so restarting the
                # settle timer on one would delay the set.
                return
            case (
                CodeOperation(current_lock_state=state)
                | LockOperation(current_lock_state=state)
                | CredentialOperation(current_lock_state=LockStatus() as state)
            ):
                status = MATCH_STATUS.get(state)
            case _:
                status = None
        if self._past_window():
            self._async_end_matching()
            return
        attribution = attribution_for(record, self._model)
        if (
            attribution is not None
            and self._changes
            and status is MATCH_STATUS[self._changes[-1].new_state.lock]
        ):
            self._candidate = attribution
        if self._candidate is not None:
            self._async_arm_settle()

    @callback
    def async_cancel(self) -> None:
        """Cancel the settle timer."""
        if self._settle_cancel is not None:
            self._settle_cancel()
            self._settle_cancel = None

    @callback
    def _async_end_matching(self) -> None:
        """Drop the candidate, its settle timer, and the change being matched."""
        self._candidate = None
        self.async_cancel()
        self._changes.clear()

    def _past_window(self) -> bool:
        """Return True once ACTIVITY_WINDOW_SECONDS have passed since the change."""
        return (
            time.monotonic() - self._change_started_monotonic > ACTIVITY_WINDOW_SECONDS
        )

    @callback
    def _async_arm_settle(self) -> None:
        """Restart the settle timer, whose end sets the candidate's cause on the change."""
        self.async_cancel()
        self._settle_cancel = async_call_later(
            self._hass, ACTIVITY_SETTLE_SECONDS, self._async_settled
        )

    @callback
    def _async_settled(self, _now: datetime) -> None:
        """Set the candidate's cause on the change, with the event first while the lock entity shows the change."""
        self._settle_cancel = None
        attribution = self._candidate
        if TYPE_CHECKING:
            assert attribution is not None
        changes = self._changes.copy()
        self._async_end_matching()
        if self._past_window():
            return
        shown = any(change.latest for change in changes)
        context = Context()
        if shown:
            # The event is fired before the set, so the logbook takes it as the origin
            # of the context the lock entity writes changed_by under.
            self._hass.bus.async_fire(
                EVENT_LOCK_ACTIVITY,
                {
                    ATTR_DEVICE_ID: self._device_id,
                    ATTR_ENTITY_ID: self._entity_id,
                    ATTR_SOURCE: attribution.source,
                    ATTR_SLOT: attribution.slot,
                    ATTR_MASTER_CODE: attribution.master_code,
                    ATTR_CHANGED_BY: attribution.changed_by,
                },
                context=context,
                time_fired=self._change_started,
            )
        for change in changes:
            change.async_set_changed_by(attribution.changed_by, context)
        if shown:
            self._times.append(time.monotonic() - self._change_started_monotonic)
            for listener in tuple(self._time_listeners):
                listener()
