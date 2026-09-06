from __future__ import annotations


def build_sku(product_id: str, category_abbreviation: str, size_abbreviation: str, color_abbreviation: str, kit_abbreviation: str, material_abbreviation: str) -> str:
    numeric_id = "".join(character for character in str(product_id) if character.isdigit())
    if not numeric_id:
        raise ValueError("O ID do produto precisa conter numeros para gerar o SKU.")
    sku = "-".join([numeric_id, category_abbreviation, size_abbreviation, color_abbreviation, kit_abbreviation, material_abbreviation]).upper()
    if len(sku) > 15:
        raise ValueError(f"O SKU gerado ({sku}) possui {len(sku)} caracteres. Reduza as abreviacoes para no maximo 15 caracteres.")
    return sku
