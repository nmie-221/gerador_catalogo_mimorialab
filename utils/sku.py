from __future__ import annotations


def build_sku(category_abbreviation: str, size_abbreviation: str, color_abbreviation: str, kit_abbreviation: str, material_abbreviation: str) -> str:
    return "-".join([category_abbreviation, size_abbreviation, color_abbreviation, kit_abbreviation, material_abbreviation]).upper()
