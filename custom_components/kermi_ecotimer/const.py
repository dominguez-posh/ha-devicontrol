"""Constants for the Kermi EcoTimer integration."""

from datetime import timedelta

DOMAIN = "kermi_ecotimer"

# The connection is kept open, so polling only costs one GATT read.
CONF_POLL_SECONDS = "poll_seconds"
DEFAULT_POLL_SECONDS = 10
MIN_POLL_SECONDS = 5
MAX_POLL_SECONDS = 3600

# Clock drift after which the device clock is set again, and how often it is checked.
CLOCK_TOLERANCE_SECONDS = 120
CLOCK_CHECK_INTERVAL = timedelta(hours=1)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
