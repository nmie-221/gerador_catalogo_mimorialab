from __future__ import annotations

from itertools import product
from typing import Any

import pandas as pd

from services.google_sheets import HEADERS, SHEETS, append_rows, now_iso, read_sheet, update_row
from utils.sku import build_sku
from utils.validators import abbreviation, clean, normalize, number, required, unique


def table(kind: str) -> pd.DataFrame:
    return read_sheet(SHEETS[kind]).copy()


def active(kind: str) -> pd.DataFrame:
    frame = table(kind)
    return frame[frame["ativo"].astype(str).str.casefold().isin(["sim", "true", "1"])]


def _next_id(kind: str, prefix: str) -> str:
    frame = table(kind)
    numbers = []
    for value in frame.get("id", frame.get("id_produto", [])):
        text = str(value)
        if text.startswith(prefix) and text[len(prefix):].isdigit():
            numbers.append(int(text[len(prefix):]))
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def add_product(name: str, category_id: str, abbrev: str, enabled: bool) -> None:
    products = table("produtos")
    clean_name = required(name, "o nome do produto")
    clean_abbrev = abbreviation(required(abbrev, "a abreviacao"))
    if not unique(products["nome_produto"], clean_name):
        raise ValueError("Ja existe um produto com esse nome.")
    if not unique(products["abreviacao"], clean_abbrev):
        raise ValueError("Ja existe um produto com essa abreviacao.")
    append_rows("PRODUTOS", [[_next_id("produtos", "P"), clean_name, category_id, clean_abbrev, "Sim" if enabled else "Nao", now_iso()]])


def add_domain(kind: str, name: str, abbrev: str, enabled: bool) -> None:
    frame = table(kind)
    clean_name = required(name, "o nome")
    clean_abbrev = abbreviation(required(abbrev, "a abreviacao"))
    if not unique(frame["nome"], clean_name):
        raise ValueError("Ja existe um registro com esse nome.")
    if not unique(frame["abreviacao"], clean_abbrev):
        raise ValueError("Ja existe um registro com essa abreviacao.")
    prefix = {"categorias": "CAT", "tamanhos": "TAM", "cores": "COR", "materiais": "MAT"}[kind]
    append_rows(SHEETS[kind], [[_next_id(kind, prefix), clean_name, clean_abbrev, "Sim" if enabled else "Nao"]])


def _product_maps() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    products = table("produtos")
    categories = table("categorias")
    product_by_id = {str(row.id_produto): str(row.abreviacao) for row in products.itertuples()}
    product_name = {str(row.id_produto): str(row.nome_produto) for row in products.itertuples()}
    category_name = {str(row.id): str(row.nome) for row in categories.itertuples()}
    return product_by_id, product_name, category_name


def variation_sku(product_id: str, size_id: str, color_id: str, kit: int, material_id: str) -> str:
    product_abbrev = _product_maps()[0][product_id]
    size = table("tamanhos").set_index("id").loc[size_id, "abreviacao"]
    color = table("cores").set_index("id").loc[color_id, "abreviacao"]
    material = table("materiais").set_index("id").loc[material_id, "abreviacao"]
    return build_sku(product_abbrev, str(size), str(color), int(kit), str(material))


def _variation_row(product_id: str, size_id: str, color_id: str, kit: int, material_id: str, price: float, cost: float, enabled: bool, note: str, sku: str) -> list[Any]:
    return [sku, product_id, size_id, color_id, int(kit), material_id, price, cost, "Sim" if enabled else "Nao", now_iso(), clean(note)]


def add_variations(rows: list[dict[str, Any]]) -> int:
    current = table("variacoes")
    existing = {normalize(value) for value in current["sku"].tolist()}
    fresh = []
    for item in rows:
        sku = str(item["sku"])
        if normalize(sku) in existing:
            continue
        fresh.append(_variation_row(**item))
        existing.add(normalize(sku))
    if fresh:
        append_rows("VARIACOES", fresh)
    return len(fresh)


def deactivate_product(product_id: str) -> None:
    products = table("produtos")
    matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
    if not matches:
        raise ValueError("Produto nao encontrado.")
    row = products.iloc[matches[0]].tolist()
    row[4] = "Nao"
    update_row("PRODUTOS", matches[0] + 2, row)


def deactivate_variation(sku: str) -> None:
    variations = table("variacoes")
    matches = variations.index[variations["sku"].astype(str).map(normalize) == normalize(sku)].tolist()
    if not matches:
        raise ValueError("Variacao nao encontrada.")
    row = variations.iloc[matches[0]].tolist()
    row[8] = "Nao"
    update_row("VARIACOES", matches[0] + 2, row)


def edit_product(product_id: str, name: str, category_id: str, abbrev: str, enabled: bool) -> None:
    products = table("produtos")
    matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
    if not matches:
        raise ValueError("Produto nao encontrado.")
    clean_name = required(name, "o nome do produto")
    clean_abbrev = abbreviation(required(abbrev, "a abreviacao"))
    current_index = matches[0]
    other_products = products.drop(index=current_index)
    if not unique(other_products["nome_produto"], clean_name):
        raise ValueError("Ja existe outro produto com esse nome.")
    if not unique(other_products["abreviacao"], clean_abbrev):
        raise ValueError("Ja existe outro produto com essa abreviacao.")
    row = products.iloc[current_index].tolist()
    row[1:5] = [clean_name, category_id, clean_abbrev, "Sim" if enabled else "Nao"]
    update_row("PRODUTOS", current_index + 2, row)


def edit_variation(original_sku: str, product_id: str, size_id: str, color_id: str, kit: int, material_id: str, price: float, cost: float, enabled: bool, note: str) -> str:
    variations = table("variacoes")
    matches = variations.index[variations["sku"].astype(str).map(normalize) == normalize(original_sku)].tolist()
    if not matches:
        raise ValueError("Variacao nao encontrada.")
    new_sku = variation_sku(product_id, size_id, color_id, int(kit), material_id)
    current_index = matches[0]
    other_skus = variations.drop(index=current_index)["sku"]
    if not unique(other_skus, new_sku):
        raise ValueError("A edicao geraria um SKU que ja existe.")
    row = _variation_row(product_id, size_id, color_id, int(kit), material_id, number(price, "O preco"), number(cost, "O custo"), enabled, note, new_sku)
    update_row("VARIACOES", current_index + 2, row)
    return new_sku


def build_variation_options(product_id: str, size_ids: list[str], color_ids: list[str], kits: list[int], material_ids: list[str], price: float, cost: float, enabled: bool, note: str) -> list[dict[str, Any]]:
    return [
        {"sku": variation_sku(product_id, size_id, color_id, kit, material_id), "product_id": product_id, "size_id": size_id, "color_id": color_id, "kit": kit, "material_id": material_id, "price": price, "cost": cost, "enabled": enabled, "note": note}
        for size_id, color_id, kit, material_id in product(size_ids, color_ids, kits, material_ids)
    ]


def catalog() -> pd.DataFrame:
    variations = table("variacoes")
    if variations.empty:
        return pd.DataFrame(columns=["SKU", "Produto", "Categoria", "Tamanho", "Cor", "Kit", "Material", "Preco", "Custo", "Lucro", "Margem %", "Ativo"])
    products = table("produtos").set_index("id_produto")
    categories = table("categorias").set_index("id")["nome"].to_dict()
    sizes = table("tamanhos").set_index("id")["nome"].to_dict()
    colors = table("cores").set_index("id")["nome"].to_dict()
    materials = table("materiais").set_index("id")["nome"].to_dict()
    result = variations.copy()
    result["Produto"] = result["id_produto"].map(products["nome_produto"].to_dict())
    result["Categoria"] = result["id_produto"].map(products["categoria_id"].map(categories).to_dict())
    result["Tamanho"] = result["tamanho_id"].map(sizes)
    result["Cor"] = result["cor_id"].map(colors)
    result["Material"] = result["material_id"].map(materials)
    result["Kit"] = pd.to_numeric(result["quantidade_kit"], errors="coerce")
    result["Preco"] = pd.to_numeric(result["preco"], errors="coerce").fillna(0)
    result["Custo"] = pd.to_numeric(result["custo"], errors="coerce").fillna(0)
    result["Lucro"] = result["Preco"] - result["Custo"]
    result["Margem %"] = result.apply(lambda row: (row["Lucro"] / row["Preco"] * 100) if row["Preco"] else 0, axis=1)
    return result.rename(columns={"sku": "SKU", "ativo": "Ativo"})[["SKU", "Produto", "Categoria", "Tamanho", "Cor", "Kit", "Material", "Preco", "Custo", "Lucro", "Margem %", "Ativo"]]


def update_entity(kind: str, row_number: int, values: list[Any]) -> None:
    update_row(SHEETS[kind], row_number, values)
