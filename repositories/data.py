from __future__ import annotations

from typing import Any

import pandas as pd

from services.google_sheets import HEADERS, SHEETS, append_rows, delete_row, now_iso, read_sheet, update_row
from repositories import catalog_dynamo as dynamo
from utils.sku import build_sku
from utils.validators import abbreviation, clean, format_ncm, ncm as valid_ncm, normalize, number, required, unique


def table(kind: str) -> pd.DataFrame:
    frame = dynamo.read(kind) if dynamo.enabled() else read_sheet(SHEETS[kind]).copy()
    for column in HEADERS[SHEETS[kind]]:
        if column not in frame.columns:  # sheets created before the newer product fields
            frame[column] = ""
    frame = frame.fillna("")
    if kind == "produtos" and dynamo.enabled() and not frame.empty:
        # The cost shown everywhere is always the live sum of the recipe, so
        # material price changes are reflected without re-saving each product.
        from repositories import production
        config = production.settings()
        items = production.materials()
        recipes = production.product_costs_many(frame["id_produto"].astype(str).tolist())
        frame = frame.copy()
        for index, row in frame.iterrows():
            costs = recipes[str(row["id_produto"])]
            if production.has_costs(costs):
                frame.at[index, "custo"] = float(production.breakdown(costs, config, items)["total"])
    return frame


def active(kind: str) -> pd.DataFrame:
    frame = table(kind)
    return frame[frame["ativo"].astype(str).str.casefold().isin(["sim", "true", "1"])]


def fresh_table(kind: str) -> pd.DataFrame:
    if not dynamo.enabled():
        read_sheet.clear()
    return table(kind)


def _next_id(prefix: str) -> str:
    values = table("produtos")["id_produto"].astype(str)
    numbers = [int(value[len(prefix):]) for value in values if value.startswith(prefix) and value[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _domain_id(kind: str, prefix: str) -> str:
    values = table(kind)["id"].astype(str)
    numbers = [int(value[len(prefix):]) for value in values if value.startswith(prefix) and value[len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _domain_row(kind: str, identifier: str, name: str, abbrev: str, enabled: bool, ncm: str) -> list:
    row = [identifier, name, abbrev, "Sim" if enabled else "Nao"]
    if kind == "categorias":
        row.append(valid_ncm(ncm))  # products inherit the NCM of their category
    return row


def add_domain(kind: str, name: str, abbrev: str, enabled: bool, ncm: str = "") -> None:
    frame = table(kind)
    name = required(name, "o nome")
    abbrev = abbreviation(required(abbrev, "a abreviacao"))
    if not unique(frame["nome"], name) or not unique(frame["abreviacao"], abbrev):
        raise ValueError("Nome e abreviacao devem ser unicos dentro do cadastro.")
    prefix = {"categorias": "CAT", "tamanhos": "TAM", "cores": "COR", "materiais": "MAT", "kits": "KIT"}[kind]
    row = _domain_row(kind, _domain_id(kind, prefix), name, abbrev, enabled, ncm)
    if dynamo.enabled():
        dynamo.insert(kind, dict(zip(HEADERS[SHEETS[kind]], row)))
    else:
        append_rows(SHEETS[kind], [row])


def _lookup(kind: str, identifier: str) -> pd.Series:
    frame = table(kind)
    matches = frame[frame["id"].astype(str) == str(identifier)]
    if matches.empty:
        raise ValueError(f"Registro de {kind} nao encontrado.")
    return matches.iloc[0]


DOMAIN_PRODUCT_FIELDS = {
    "categorias": "categoria", "tamanhos": "tamanho", "cores": "cor",
    "materiais": "material", "kits": "qtd_kit",
}


def domain_in_use(kind: str, identifier: str) -> bool:
    products = fresh_table("produtos")
    return products[DOMAIN_PRODUCT_FIELDS[kind]].astype(str).eq(str(identifier)).any()


def fiscal_in_use(kind: str, code: str) -> bool:
    from repositories.fiscal import KINDS
    products = fresh_table("produtos")
    return products[KINDS[kind]["field"]].astype(str).eq(str(code)).any()


def _domain_record(kind: str, identifier: str) -> tuple[pd.DataFrame, int]:
    if kind not in DOMAIN_PRODUCT_FIELDS:
        raise ValueError("Cadastro auxiliar inválido.")
    frame = fresh_table(kind)
    matches = [i for i, value in enumerate(frame["id"]) if str(value) == str(identifier)]
    if len(matches) != 1:
        raise ValueError("Registro não encontrado ou ID duplicado. Atualize a página.")
    return frame, matches[0]


def edit_domain(kind: str, identifier: str, name: str, abbrev: str, enabled: bool, ncm: str = "") -> None:
    frame, position = _domain_record(kind, identifier)
    name = required(name, "o nome")
    abbrev = abbreviation(required(abbrev, "a abreviacao"))
    others = frame.iloc[[i for i in range(len(frame)) if i != position]]
    if not unique(others["nome"], name) or not unique(others["abreviacao"], abbrev):
        raise ValueError("Nome e abreviacao devem ser unicos dentro do cadastro.")
    if abbrev != str(frame.iloc[position]["abreviacao"]) and domain_in_use(kind, identifier):
        raise ValueError("A abreviação está vinculada a produtos e não pode ser alterada para preservar os SKUs existentes.")
    row = _domain_row(kind, identifier, name, abbrev, enabled, ncm)
    if dynamo.enabled():
        dynamo.update(kind, dict(zip(HEADERS[SHEETS[kind]], row)))
    else:
        update_row(SHEETS[kind], position + 2, row)


def delete_domain(kind: str, identifier: str) -> None:
    _, position = _domain_record(kind, identifier)
    if domain_in_use(kind, identifier):
        raise ValueError("Este item está vinculado a produtos. Desative-o na edição em vez de excluir.")
    if dynamo.enabled():
        dynamo.remove(kind, identifier)
    else:
        delete_row(SHEETS[kind], position + 2)


def build_product_sku(product_id: str, category_id: str, size_id: str, color_id: str, material_id: str, kit_id: str) -> str:
    category = _lookup("categorias", category_id)
    size = _lookup("tamanhos", size_id)
    color = _lookup("cores", color_id)
    material = _lookup("materiais", material_id)
    kit = _lookup("kits", kit_id)
    return build_sku(product_id, str(category["abreviacao"]), str(size["abreviacao"]), str(color["abreviacao"]), str(kit["abreviacao"]), str(material["abreviacao"]))


PRODUCT_TEXT_FIELDS = ["cfop_estadual", "cfop_interestadual", "csosn", "origem"]
PRODUCT_MEASURES = {
    "peso_liquido_g": "Peso líquido", "peso_bruto_g": "Peso bruto com embalagem",
    "altura_cm": "Altura do pacote", "largura_cm": "Largura do pacote", "comprimento_cm": "Comprimento do pacote",
}


def _product_record(product_id: str, values: dict, sku: str, cost: float, previous: dict | None) -> dict:
    """Validate the product form values and build the stored record."""
    record = {column: "" for column in _headers()}
    record.update(id_produto=product_id, nome_produto=clean(values["nome_produto"]), sku=sku)
    for field in ["categoria", "tamanho", "cor", "material", "qtd_kit"]:
        record[field] = values[field]
    record["preco"] = number(values["preco"], "O preco")
    record["custo"] = round(float(cost), 2)
    record["imagem_url"] = clean(values.get("imagem_url", ""))
    # Barcodes are no longer edited, but existing values are never erased.
    record["codigo_barras"] = clean((previous or {}).get("codigo_barras", ""))
    for field in PRODUCT_TEXT_FIELDS:
        record[field] = clean(values.get(field, ""))
    for field, label in PRODUCT_MEASURES.items():
        record[field] = number(values.get(field) or 0, label)
    if record["peso_liquido_g"] and record["peso_bruto_g"] and record["peso_bruto_g"] < record["peso_liquido_g"]:
        raise ValueError("O peso bruto (com embalagem de envio) não pode ser menor que o peso líquido.")
    on_demand = bool(values.get("sob_encomenda"))
    days = number(values.get("dias_producao") or 0, "Dias de produção") if on_demand else 0
    if on_demand and (days < 1 or days != int(days)):
        raise ValueError("Informe os dias de produção (número inteiro maior que zero) para produtos sob encomenda.")
    record["sob_encomenda"] = "Sim" if on_demand else "Nao"
    record["dias_producao"] = int(days)
    return record


def _headers() -> list[str]:
    from services.google_sheets import HEADERS
    return HEADERS["PRODUTOS"]


def _money_series(values: pd.Series) -> pd.Series:
    def parse(value: object) -> float:
        try:
            return number(value or 0, "O valor")
        except ValueError:
            return 0.0

    return values.map(parse).astype("float64")


def save_product(product_id: str | None, values: dict, costs: dict) -> tuple[str, str]:
    """Create (product_id=None) or edit a product together with its recipe.

    The stored cost is the sum of the recipe. With DynamoDB the product and its
    recipe are written in one transaction, so neither is saved without the other.
    Returns (product_id, sku).
    """
    from repositories import production
    products = fresh_table("produtos")
    name = required(values.get("nome_produto"), "o nome do produto")
    missing = [label for field, label in [("categoria", "Categoria"), ("tamanho", "Tamanho"), ("cor", "Cor/tema"), ("material", "Material"), ("qtd_kit", "Kit")] if not values.get(field)]
    if missing:
        raise ValueError(f"Preencha os campos obrigatórios: {', '.join(missing)}.")
    previous = None
    others = products
    if product_id:
        matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
        if not matches:
            raise ValueError("Produto nao encontrado.")
        previous = products.loc[matches[0]].to_dict()
        others = products.drop(index=matches[0])
    else:
        product_id = _next_id("P")
    if not unique(others["nome_produto"], name):
        raise ValueError("Ja existe outro produto com esse nome.")
    sku = build_product_sku(product_id, values["categoria"], values["tamanho"], values["cor"], values["material"], values["qtd_kit"])
    if not unique(others["sku"], sku):
        raise ValueError("Ja existe um produto com esse SKU." if previous is None else "A edicao geraria um SKU que ja existe.")
    pk, sk = production.costs_key(product_id)
    recipe = dict(costs, PK=pk, SK=sk)
    if previous is None:
        # A leftover recipe from an old product with the same ID is replaced.
        recipe["revision"] = production.product_costs(product_id)["revision"]
    recipe_item, expected = production.prepare_product_costs(recipe)
    cost = production.breakdown(recipe_item, production.settings(), production.materials())["total"]
    record = _product_record(product_id, dict(values, nome_produto=name), sku, cost, previous)
    if dynamo.enabled():
        if previous is None:
            dynamo.insert("produtos", record, extra=[(recipe_item, expected)])
        else:
            dynamo.update("produtos", record, extra=[(recipe_item, expected)])
        return product_id, sku
    production.store.put(recipe_item, expected)
    row = [record[column] for column in _headers()]
    if previous is None:
        append_rows("PRODUTOS", [row])
    else:
        update_row("PRODUTOS", matches[0] + 2, row)
    return product_id, sku


def delete_product(product_id: str) -> None:
    from repositories import production
    products = fresh_table("produtos")
    matches = products.index[products["id_produto"].astype(str) == str(product_id)].tolist()
    if not matches:
        raise ValueError("Produto nao encontrado.")
    costs = production.product_costs(product_id)
    if costs.get("has_production"):
        raise ValueError("Produto com produção registrada: exclusão bloqueada para preservar o histórico. Mantenha-o cadastrado.")
    recipe_keys = [production.costs_key(product_id)] if costs["revision"] else []
    if dynamo.enabled():
        dynamo.remove("produtos", product_id, extra_keys=recipe_keys)
    else:
        delete_row("PRODUTOS", matches[0] + 2)
        if recipe_keys:
            production.store.delete(*recipe_keys[0])


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
    result["Preco"] = _money_series(result["preco"])
    result["Custo"] = _money_series(result["custo"])
    result["Lucro"] = result["Preco"] - result["Custo"]
    result["Margem %"] = result.apply(lambda row: row["Lucro"] / row["Preco"] * 100 if row["Preco"] else 0, axis=1)
    category_ncm = table("categorias").set_index("id")["ncm"].to_dict()
    result["NCM"] = result["categoria"].map(category_ncm).fillna("").map(format_ncm)
    result["Peso bruto (g)"] = _money_series(result["peso_bruto_g"])
    dimensions = zip(*(_money_series(result[c]) for c in ["altura_cm", "largura_cm", "comprimento_cm"]))
    result["Pacote (cm)"] = [" x ".join(f"{v:g}" for v in sizes) if any(sizes) else "" for sizes in dimensions]
    result["Produção (dias)"] = result.apply(lambda row: str(row["dias_producao"]) if str(row["sob_encomenda"]) == "Sim" else "Pronta entrega", axis=1)
    return result[["id_produto", "nome_produto", "Categoria", "Tamanho", "Cor", "Material", "Kit", "sku", "imagem_url", "Preco", "Custo", "Lucro", "Margem %", "NCM", "Peso bruto (g)", "Pacote (cm)", "Produção (dias)"]]
