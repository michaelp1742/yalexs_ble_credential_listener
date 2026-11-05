# Yale Access Bluetooth Credential Listener

A proof of concept of a parallel integration to `yalexs_ble`, Home Assistant's
[Yale Access Bluetooth](https://www.home-assistant.io/integrations/yalexs_ble/) integration. It names the cause of a
lock change in the lock entity's `changed_by`: the keypad slot, the master code, the RF tag, the keypad's button,
the inside button, a command over Bluetooth, or the lock's own relock. It reads the cause from the lock's activity log,
through Yale Access Bluetooth's connection to the lock, and hands it to Yale Access Bluetooth's lock entity through an
interface in that integration. It has no PIN actions, changes no PIN on the lock, and stores no names.

## What it shows

A parallel integration can attribute the changes of a lock entity it does not own. Yale Access Bluetooth's lock entity
writes every change of the lock status at once, with `changed_by` cleared, and then tells every registered attributor
of the change. An attributor that learns the cause sets `changed_by` on that change, once, under a context of its own,
and the lock entity writes the attribute. Yale Access Bluetooth keeps no matching rule and no words of its own: this
integration decides which changes it names, how long it waits for a record, and what the cause is called.

This integration is that attributor for the activity log. It applies the credential matching of
[home-assistant/core#185596](https://github.com/home-assistant/core/pull/185596) through the interface, names an RF tag
as well, and measures how long each cause takes to arrive.

## Requirements

- Home Assistant 2026.10.0 or later.
- The Yale Access Bluetooth integration, set up for the lock, with the attribution interface: a `helpers` module with
  `async_register_attributor`, and a lock entity that tells the registered attributors of each change of the lock
  status. No Home Assistant release has it yet. Until a pull request to Home Assistant adds it, the interface is a
  patch to Yale Access Bluetooth, installed as a custom integration in `custom_components/yalexs_ble`, whose manifest
  needs a `version` key for Home Assistant to load it in place of the built-in integration.
- yalexs-ble from [Yale-Libs/yalexs-ble#426](https://github.com/Yale-Libs/yalexs-ble/pull/426) on, or a release that
  contains it, for `register_log_record_callback` and `parse_log_event_packet`. The yalexs-ble that Home Assistant
  2026.10 installs, 4.0.1, has neither, and with it Home Assistant cannot load this integration and logs an
  `ImportError`.
- With a yalexs-ble that has both but without the interface, adding this integration aborts, and an existing entry with
  its option on logs a warning and attributes nothing.
- At each start, Home Assistant installs the yalexs-ble version that Yale Access Bluetooth pins, in place of any
  other. Another version stays installed when Home Assistant runs with `--skip-pip-packages yalexs-ble`, or with
  `--skip-pip`, which skips the requirements of every integration.
- yalexs-ble from #426 requires cryptography 50.0.2 or later. Home Assistant 2026.11 pins cryptography 50.0.2.
  Home Assistant 2026.10 pins cryptography 50.0.1, so on 2026.10 no cryptography version meets both.

## Installation

With [HACS](https://hacs.xyz/):

1. In HACS, open the menu at the top right and pick **Custom repositories**.
2. Add `https://github.com/michaelp1742/yalexs_ble_credential_listener` with the type **Integration**.
3. Find **Yale Access Bluetooth Credential Listener** in HACS, download it, and restart Home Assistant.

Without HACS, copy `custom_components/yalexs_ble_credential_listener` into the `custom_components` folder of your
Home Assistant configuration, then restart Home Assistant.

## Setup

1. In **Settings** > **Devices & services**, add **Yale Access Bluetooth Credential Listener**.
2. Pick the lock. The list shows each lock that Yale Access Bluetooth has loaded and that has no credential listener
   entry yet.
3. Pick the lock's model. No model is picked in advance, and nothing is read from the lock to guess it.

The entry starts with its option off. It then adds no entity and reads nothing from the lock. The model can be changed
later in the entry's options.

## The lock models

The model gives the slot and PIN parameters established for the lock. This integration reads only the master code's
slot, at which a code is named "Master code"; the other values are not read. A blank is a value not established.

| Model | First PIN slot | Last PIN slot | Master code slot | PIN length |
|---|---|---|---|---|
| Yale Unity Entrance Lock | 1 | 100 | `0xFFEE` | 6 |
| Yale Assure Lock SL (YRD256) with a network module | 1 | 250 | `0xFFEE` | 4 to 8 |
| Yale Doorman Classic (V2N) with the Yale Access Module | 0 | 9 | | 6 |
| Yale Doorman L3 | | | | 6 to 10 |
| Not listed | | | | |

## The attribution option

In the entry's options, turn on **Attribute lock changes from the activity log**.

Home Assistant reads each record off the lock. A record it reads never reaches the Yale Home or August app's activity
feed or the cloud.

With the option on, Yale Access Bluetooth's lock entity still writes each change at once, and this integration names
the cause of a change to locked or unlocked that Home Assistant did not command, from the lock's record of it. When a
record that names the cause has arrived, and no further record has come for 0.75 seconds, this integration fires its
event and sets `changed_by` on the change. The state's `last_changed` stays at the lock change; the set changes the
attribute and `last_updated`.

The cause follows the change. In field tests on a Yale Unity Entrance Lock every cause was set 0.8 to 2.9 seconds
after its change, over 27 changes: the keypad, the fingerprint, three RF tags, the inside button, the Yale Home app
and the lock's relock. By the record times in captures on that lock, a change with one record, such as a command over
Bluetooth, the inside button, or an RF tag, is named about 1.3 to 1.5 seconds after it, and a keypad code, which writes
two records, about 2 seconds after it, or up to about 2.8 seconds when the library's status poll runs between the two
reads. The sensors below measure the times on a running lock.

So an automation that needs the cause triggers on the lock's `changed_by` attribute, or on the event below. An
automation triggered by a change of the lock's state, such as a state trigger with `to: unlocked`, runs before the
cause is set and finds no `changed_by` attribute. A state trigger with no `to`, `from`, or `attribute` runs at the
change and again when the cause is set. A trigger on the `changed_by` attribute runs when the cause is set, and also
when a change clears the cause of the change before it, so an automation on the attribute names the cause it wants
with `to`, such as `to: Keypad slot 1`, or checks in a condition that `changed_by` has a value.

A change Home Assistant commanded is written with `changed_by` cleared and is given no cause. Each new change, a
commanded one included, ends the matching of the change before it, so the record of the earlier change sets no cause
on it. A change with no record that names it within 10 seconds keeps no cause, and a record read later names no
change.

An unlock from the Yale Home app is named "Remote" when Home Assistant reads its record. While the app is connected to
the lock, it can read the record first, and the unlock then has no cause.

Turning the option off reloads the entry, which then reads nothing from the lock, and the lock entity writes every
change with no cause. The two sensors stay, shown as unavailable, and keep their history.

## What `changed_by` says

Slots are numbered in decimal, as the keypad numbers them.

| Cause | `changed_by` | Logbook |
|---|---|---|
| A keypad code at slot N | Keypad slot N | keypad slot N used |
| The master code, at the model's master code slot | Master code | master code used |
| An RF tag at slot N | RF tag slot N | RF tag slot N used |
| The keypad's Yale button with One-Touch Lock on | Keypad | keypad used |
| The inside button, or the lock turned by hand | Manual | operated manually |
| A command over Bluetooth that Home Assistant did not send, such as from the Yale Home app | Remote | operated remotely |
| The lock's own relock | Auto lock | auto locked |

A code for a model with no master code slot in the table is named by its slot. A fingerprint at the Yale Smart Keypad
2 - Fingerprint arrives as a code at the slot of the PIN associated with it, so it reads "Keypad slot N". A record
of a fingerprint, face, palm, or Aliro credential type names no cause, and the change keeps none.

## The event

This integration fires the event `yalexs_ble_credential_listener_lock_activity` just before it sets the cause, while
the lock entity still shows the change. The event's time is the lock change's, and its context is new; the lock entity
writes `changed_by` under that context. The logbook shows the event at the time of the change, under the name of the
lock's device, for example "Front Door keypad slot 1 used". Its data:

| Key | Value |
|---|---|
| `device_id` | the Yale Access Bluetooth device of the lock |
| `entity_id` | the Yale Access Bluetooth lock entity |
| `source` | `pin`, `rf`, `manual`, `remote`, or `auto_lock` |
| `slot` | the slot number, or `null` for the master code and for a cause with no slot |
| `master_code` | `true` for the master code |
| `changed_by` | the text set as `changed_by` |

## The sensors

With the option on, the entry adds two diagnostic sensors, **Attribution time median** and **Attribution time
maximum**, on a device of the entry's own, which has the same Bluetooth connection as the Yale Access Bluetooth device
for the lock. A time runs from a lock change to the set of its cause: how long the lock entity showed the change
without its cause, which is how late an automation on `changed_by` runs.

- The sensors show the median and the maximum, in seconds to two decimals, of the last 1000 times since the entry
  loaded.
- Their `samples` attribute is the count of those times.
- They are unknown until the first time, and a reload of the entry or a restart of Home Assistant starts them afresh.
- The maximum stays under 10 seconds, since a cause is set only within 10 seconds of its change.

## Icon

The integration's icon is drawn from the account tag icon (`mdi-account-tag`) of Material Design Icons by
[Pictogrammers](https://pictogrammers.com/), which is under the Apache License 2.0.

## Development

```sh
uv venv --python 3.14
uv pip install -r requirements_test.txt
script/build-hook-copy.sh <a core repository with the attribution interface> [<commit>]
.venv/bin/python -m pytest
.venv/bin/pre-commit run --all-files
```

`script/build-hook-copy.sh` builds `tests/hook/custom_components/yalexs_ble`, a git-ignored copy of Yale Access
Bluetooth with the attribution interface and a `version` key, which `tests/test_hook.py` loads as a custom integration
and drives this integration's matching through the copy's lock entities. Without the copy, those tests are skipped.
