# Backward-compatible re-export. Prefer app.services.setup.
from app.services.setup import (  # noqa: F401
    PRESETS,
    apply_setup,
    discover_rules_only,
    discover_setup,
    list_presets_public,
    suggest_from_description,
    suggest_with_ai,
)
