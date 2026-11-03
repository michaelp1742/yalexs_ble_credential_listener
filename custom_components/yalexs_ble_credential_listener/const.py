"""Constants for the Yale Access Bluetooth Credential Listener integration."""

DOMAIN = "yalexs_ble_credential_listener"
OWNER_DOMAIN = "yalexs_ble"
CONF_ATTRIBUTION = "attribution"
CONF_LOCK_MODEL = "lock_model"
EVENT_LOCK_ACTIVITY = "yalexs_ble_credential_listener_lock_activity"

# A record read later than this after a change, such as a relock read on a
# reconnect's drain, names no change.
ACTIVITY_WINDOW_SECONDS = 10.0
# home-assistant/core#185596's wait for no further record.
ACTIVITY_SETTLE_SECONDS = 0.75

ATTR_MASTER_CODE = "master_code"
ATTR_SLOT = "slot"
ATTR_SOURCE = "source"

SOURCE_AUTO_LOCK = "auto_lock"
SOURCE_MANUAL = "manual"
SOURCE_PIN = "pin"
SOURCE_REMOTE = "remote"
SOURCE_RF = "rf"
