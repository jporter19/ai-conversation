# app/services/setup — provider onboarding / discovery.
from app.services.setup.apply import apply_setup
from app.services.setup.discover import discover_setup, suggest_with_ai
from app.services.setup.presets import PRESETS, list_presets_public
from app.services.setup.rules import discover_rules_only, suggest_from_description

__all__ = [
    "PRESETS",
    "apply_setup",
    "discover_rules_only",
    "discover_setup",
    "list_presets_public",
    "suggest_from_description",
    "suggest_with_ai",
]
