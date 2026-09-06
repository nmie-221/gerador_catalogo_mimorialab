from __future__ import annotations


def build_sku(product_abbreviation: str, size_abbreviation: str, color_abbreviation: str, kit: int, material_abbreviation: str) -> str:
    return f"{product_abbreviation}-{size_abbreviation}-{color_abbreviation}-{int(kit)}-{material_abbreviation}"
