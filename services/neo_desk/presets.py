from .types import NeoPreset

PRESETS = {
    "orb_trail": NeoPreset("orb_trail", "ORB · index trail · 6R", "orb15"),
    "orb_controls": NeoPreset(
        "orb_controls", "ORB · option controls · 6R", "orb15", controlled=True
    ),
    "donchian_controls": NeoPreset(
        "donchian_controls",
        "Donchian · trend / option controls · 6R",
        "donchian",
        ema_filter=True,
        controlled=True,
    ),
    "price_retest": NeoPreset(
        "price_retest",
        "Price Break & Retest · Sandbox research · 6R",
        "price_retest",
        controlled=True,
        research_only=True,
    ),
}


def get_preset(profile):
    if profile not in PRESETS:
        raise ValueError("Choose one of the four installed presets.")
    return PRESETS[profile]
