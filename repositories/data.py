from __future__ import annotations

from typing import Any

import pandas as pd

from services.google_sheets import SHEETS, append_rows, now_iso, read_sheet, update_row
from utils.sku import build_sku
from utils.validators import abbreviation, clean, normalize, number, required, unique


def table(kind: str) -> pd.DataFrame:
    return read_sheet(SHEETS[kind]).copy()


def active(kind: str) -> pd.DataFrame:
    frame = table(kind)
    return frame[frame["ativo"].astype(str).str.casefold().isin(["sim", "true", "1"])]


def _next_id(prefix: str) -> str:
    values = table("produtos")["id_produto"].astype(str)
    numbers = [int(value[len(prefix):]) for value in values if value.startswith(prefix) and value[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _domain_id(kind: str, prefix: str) -> str:
    values = table(kind)["id"].astype(str)
    numbers = [int(value[len(prefix):]) for value in values if value.startswith(prefix) and value[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def add_domain(kind: str, name: str, abbrev: str, enabled: bool) -> None:
    frame = table(kind)
    name = required(name, "o nome")
    abbrev = abbreviation(required(abbrev, "a abreviacao"))
    if not unique(frame["nome"], name) or not unique(frame["abreviacao"], abbrev):
        raise ValueError("Nome e abreviacao devem ser unicos dentro do cadastro.")
    prefix = {"categorias": "CAT", "tamanhos": "TAM", "cores": "COR", "materiais": "MAT", "kits": "KIT"}[kind]
    append_rows(SHEETS[kind], [[_domain_id(kind, prefix), name, abbrev, "Sim" if enabled else "Nao"]])


def _lookup(kind: str, identifier: str) -> pd.Series:
    frame = table(kind)
    matches = frame[frame["id"].astype(str) == str(identifier)]
    if matches.empty:
        raise ValueError(f"Registro de {kind} nao encontrado.")
    return matches.iloc[0]


def build_product_sku(product_id: str, category_id: str, size_id: str, color_id: str, material_id: str, kit_id: str) -> str:
    category = _lookup("categorias", category_id)
    size = _lookup("tamanhos", size_id)
    color = _lookup("cores", color_id)
    material = _lookup("materiais", material_id)
    kit = _lookup("kits", kit_id)
    return build_sku(product_id, str(category["abreviacao"]), str(size["abreviacao"]), str(color["abreviacao"]), str(kit["abreviacao"]), str(material["abreviacao"]))


def _product_row(product_id: str, name: str, category_id: str, size_id: str, color_id: str, material_id: str, price: float, cost: float, kit_id: str, barcode: str, sku: str) -> list[Any]:
    return [product_id, clean(name), category_id, size_id, color_id, material_id, number(price, "O preco"), number(cost, "O custo"), kit_id, sku, clean(barcode)]


def add_product(name: str, category_id: str, size_id: str, color_id: str, material_id: str, price: float, cost: float, kit_id: str, barcode: str) -> str:
    products = table("produtos")
    name = required(name, "o nome do produto")
    if not unique(products["nome_produto"], name):
        raise ValueError("Ja existe um produto com esse nome.")
    product_id = _next_id("P")
    sku = build_product_sku(product_id, category_id, size_id, color_id, material_id, kit_id)
    if not unique(products["sku"], sku):
        raise ValueError("Ja existe um produto com esse SKU.")
    append_rows("PRODUTOS", [_product_row(product_id, name, category_id, size_id, color_id, material_id, price, cost, kit_id, barcode, sku)])
    return sku


def edit_product(product_id: str, name: str, category_id: str, size_id: str, color_id: str, material_id: str, price: float, cost: float, kit_id: str, barcode: str) -> str:
    products = table("produtos")
    matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
    if not matches:
        raise ValueError("Produto nao encontrado.")
    index = matches[0]
    name = required(name, "o nome do produto")
    others = products.drop(index=index)
    if not unique(others["nome_produto"], name):
        raise ValueError("Ja existe outro produto com esse nome.")
    sku = build_product_sku(product_id, category_id, size_id, color_id, material_id, kit_id)
    if not unique(others["sku"], sku):
        raise ValueError("A edicao geraria um SKU que ja existe.")
    row = _product_row(product_id, name, category_id, size_id, color_id, material_id, price, cost, kit_id, barcode, sku)
    update_row("PRODUTOS", index + 2, row)
    return sku


def delete_product(product_id: str) -> None:
    products = table("produtos")
    matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
    if not matches:
        raise ValueError("Produto nao encontrado.")
    from services.google_sheets import delete_row
    delete_row("PRODUTOS", matches[0] + 2)


def catalog() -> pd.DataFrame:
    products = table("produtos")
    if products.empty:
        return products
    categories = table("categorias").set_index("id")["nome"].to_dict()
    sizes = table("tamanhos").set_index("id")["nome"].to_dict()
    colors = table("cores").set_index("id")["nome"].to_dict()
    materials = table("materiais").set_index("id")["nome"].to_dict()
    kits = table("kits").set_index("id")["nome"].to_dict()
    result = products.copy()
    result["Categoria"] = result["categoria"].map(categories)
    result["Tamanho"] = result["tamanho"].map(sizes)
    result["Cor"] = result["cor"].map(colors)
    result["Material"] = result["material"].map(materials)
    result["Kit"] = result["qtd_kit"].map(kits)
    result["Preco"] = pd.to_numeric(result["preco"], errors="coerce").fillna(0)
    result["Custo"] = pd.to_numeric(result["custo"], errors="coerce").fillna(0)
    result["Lucro"] = result["Preco"] - result["Custo"]
    result["Margem %"] = result.apply(lambda row: row["Lucro"] / row["Preco"] * 100 if row["Preco"] else 0, axis=1)
    return result[["id_produto", "nome_produto", "Categoria", "Tamanho", "Cor", "Material", "Kit", "sku", "codigo_barras", "Preco", "Custo", "Lucro", "Margem %"]]
