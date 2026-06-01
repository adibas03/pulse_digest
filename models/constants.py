# models/constants.py
"""Shared constants for pulse_digest. Single source of truth for enums
used across models, detectors, channels, views, and tests.

Plain string constants (not enum.Enum) because Odoo's fields.Selection
expects [(value, label), ...] tuples of plain strings — matching the
framework's grain avoids conversion at every boundary.
"""

# Severity levels, ordered low -> high.
SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

SEVERITY_SELECTION = [
    (SEVERITY_INFO, "Info"),
    (SEVERITY_WARNING, "Warning"),
    (SEVERITY_CRITICAL, "Critical"),
]

# Tuple of valid values, for validation and tests.
SEVERITIES = tuple(value for value, _label in SEVERITY_SELECTION)

# Ordering helper — useful for sorting findings by urgency.
SEVERITY_ORDER = {SEVERITY_INFO: 0, SEVERITY_WARNING: 1, SEVERITY_CRITICAL: 2}
