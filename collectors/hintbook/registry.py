"""Adapter registry."""

from collectors.hintbook.adapters import (
    eatdrinkdeals,
    dealnews,
    fooddealnow,
    kcl,
    hip2save,
    slickdeals,
    retailmenot,
    bitehunter,
    broader_industries,
)

FOOD_ADAPTERS = [
    eatdrinkdeals,
    dealnews,
    fooddealnow,
    kcl,
    hip2save,
    slickdeals,
    retailmenot,
    bitehunter,
]

BROADER_ADAPTERS = [
    broader_industries,
]

ALL_ADAPTERS = FOOD_ADAPTERS + BROADER_ADAPTERS
