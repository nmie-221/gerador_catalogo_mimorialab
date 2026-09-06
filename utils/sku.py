from __future__ import annotations

import re


def build_sku(product_id: str, category_abbreviation: str, size_abbreviation: str, color_abbreviation: str, kit_abbreviation: str, material_abbreviation: str) -> str:
    numeric_id = "".join(character for character in str(product_id) if character.isdigit())
    if not numeric_id:
        raise ValueError("O ID do produto precisa conter numeros para gerar o SKU.")
    parts = [category_abbreviation, size_abbreviation, color_abbreviation, kit_abbreviation, material_abbreviation]
    for part in parts:
        normalized = str(part).strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{1,4}", normalized):
            raise ValueError(f"A abreviacao '{part}' deve conter de 1 a 4 letras ou numeros.")
    sku = numeric_id + "".join(str(part).strip().upper() for part in parts)
    if len(sku) > 15:
        raise ValueError(f"O SKU gerado ({sku}) possui {len(sku)} caracteres. Reduza as abreviacoes; cada uma pode ter no maximo 4 caracteres e o total deve ser de ate 15.")
    return sku
