from __future__ import annotations

import re
import unicodedata


def _sku_part(value: object, label: str) -> str:
    # Legacy spreadsheet entries may contain accents or surrounding whitespace.
    normalized = unicodedata.normalize("NFKD", str(value or "").strip())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char)).upper()
    normalized = re.sub(r"\s+", "", normalized)
    if not re.fullmatch(r"[A-Z0-9]{1,4}", normalized):
        raise ValueError(
            f"A abreviação de {label} ('{value}') deve conter de 1 a 4 letras ou números. "
            "Corrija o cadastro auxiliar antes de salvar o produto."
        )
    return normalized


def build_sku(product_id: str, category_abbreviation: str, size_abbreviation: str, color_abbreviation: str, kit_abbreviation: str, material_abbreviation: str) -> str:
    numeric_id = "".join(character for character in str(product_id) if character.isdigit())
    if not numeric_id:
        raise ValueError("O ID do produto precisa conter números para gerar o SKU.")
    parts = (
        ("categoria", category_abbreviation),
        ("tamanho", size_abbreviation),
        ("cor", color_abbreviation),
        ("kit", kit_abbreviation),
        ("material", material_abbreviation),
    )
    return numeric_id + "".join(_sku_part(value, label) for label, value in parts)
