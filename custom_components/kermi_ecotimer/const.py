"""Constants for the Kermi EcoTimer integration."""

DOMAIN = "kermi_ecotimer"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 5  # minutes
MIN_SCAN_INTERVAL = 1
MAX_SCAN_INTERVAL = 60

# Clock drift after which the device clock is set again.
CLOCK_TOLERANCE_SECONDS = 120

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
