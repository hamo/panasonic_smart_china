"""Shared helpers for Panasonic Smart China platform modules."""


def as_int(value, default=None):
    """Coerce a protocol value (str/int/None) to int, falling back on error."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def feature_supported(data, feature) -> bool:
    """Return whether the device supports a gated feature (unknown -> yes).

    Features declare an optional capability field (e.g. ``cleanSetEx``)
    whose truthy value in the status bean gates entity creation.
    """
    if not feature.capability:
        return True
    if not data:
        return True
    return as_int(data.get(feature.capability)) == 1