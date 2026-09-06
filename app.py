from __future__ import annotations

import pandas as pd
import streamlit as st

from repositories.data import (
    active,
    add_domain,
    add_product,
    add_variations,
    build_variation_options,
    catalog,
    table,
    variation_sku,
)
from services.google_sheets import HEADERS, SHEETS, SheetsError
from utils.validators import number

st.set_page_config(page_title="Catálogo de Produtos", page_icon="📦", layout="wide")


def error_message(action):
    try:
        return action()
    except (SheetsError, ValueError, KeyError) as exc:
        st.error(str(exc))
        return False


def selector(frame: pd.DataFrame, label: str, value_column: str = "nome") -> str | None:
    if frame.empty:
        st.warning(f"Nenhum registro ativo disponível para {label.lower()}.")
        return None
    options = {f"{row[value_column]} ({row['id']})": row["id"] for _, row in frame.iterrows()}
    selected = st.selectbox(label, list(options))
    return options[selected]


def dashboard() -> None:
    st.title("Dashboard")
    try:
        products, variations, categories, materials = (active(kind) for kind in ("produtos", "variacoes", "categorias", "materiais"))
        columns = st.columns(5)
        for column, label, value in zip(columns, ["Produtos ativos", "SKUs totais", "Categorias", "Materiais", "Variações ativas"], [len(products), len(table("variacoes")), len(categories), len(materials), len(variations)]):
            column.metric(label, value)
        st.subheader("Últimos cadastros")
        latest = table("variacoes").tail(10)
        st.dataframe(latest[["sku", "id_produto", "data_cadastro"]], use_container_width=True, hide_index=True)
    except SheetsError as exc:
        st.error(str(exc))


def products_page() -> None:
    st.title("Produtos")
    categories = active("categorias")
    with st.form("produto"):
        name = st.text_input("Nome do produto")
        category = selector(categories, "Categoria")
        abbreviation = st.text_input("Abreviação")
        enabled = st.checkbox("Ativo", value=True)
        submitted = st.form_submit_button("Cadastrar produto")
    if submitted and category:
        if error_message(lambda: add_product(name, category, abbreviation, enabled)) is not False:
            st.success("Produto cadastrado com sucesso.")
            st.rerun()
    st.dataframe(table("produtos"), use_container_width=True, hide_index=True)


def variations_page() -> None:
    st.title("Variações")
    products, sizes, colors, materials = (active(kind) for kind in ("produtos", "tamanhos", "cores", "materiais"))
    tabs = st.tabs(["Cadastro individual", "Gerar variações em lote"])
    with tabs[0]:
        with st.form("variacao"):
            product_id = selector(products, "Produto")
            size_id = selector(sizes, "Tamanho")
            color_id = selector(colors, "Cor")
            kit = st.number_input("Quantidade do kit", min_value=1, step=1, value=1)
            material_id = selector(materials, "Material")
            price = st.number_input("Preço", min_value=0.0, step=0.01, format="%.2f")
            cost = st.number_input("Custo", min_value=0.0, step=0.01, format="%.2f")
            note = st.text_area("Observação")
            enabled = st.checkbox("Variação ativa", value=True)
            submitted = st.form_submit_button("Cadastrar variação")
        if product_id and size_id and color_id and material_id:
            sku = variation_sku(product_id, size_id, color_id, int(kit), material_id)
            st.info(f"SKU: **{sku}**")
            if submitted:
                result = error_message(lambda: add_variations([{"sku": sku, "product_id": product_id, "size_id": size_id, "color_id": color_id, "kit": int(kit), "material_id": material_id, "price": price, "cost": cost, "enabled": enabled, "note": note}]))
                if result == 0:
                    st.warning("Essa combinação já está cadastrada.")
                elif result is not False and result is not None:
                    st.success("Variação cadastrada com sucesso.")
                    st.rerun()
    with tabs[1]:
        product_id = selector(products, "Produto do lote")
        size_ids = st.multiselect("Tamanhos", sizes["id"].tolist(), format_func=lambda item: sizes.set_index("id").loc[item, "nome"])
        color_ids = st.multiselect("Cores", colors["id"].tolist(), format_func=lambda item: colors.set_index("id").loc[item, "nome"])
        kits = st.multiselect("Quantidades de kit", [1, 5, 10, 20, 50, 100])
        material_ids = st.multiselect("Materiais", materials["id"].tolist(), format_func=lambda item: materials.set_index("id").loc[item, "nome"])
        price = st.number_input("Preço padrão", min_value=0.0, step=0.01, key="batch_price")
        cost = st.number_input("Custo padrão", min_value=0.0, step=0.01, key="batch_cost")
        note = st.text_input("Observação do lote")
        enabled = st.checkbox("Variações do lote ativas", value=True)
        if product_id and size_ids and color_ids and kits and material_ids:
            rows = build_variation_options(product_id, size_ids, color_ids, kits, material_ids, price, cost, enabled, note)
            existing = set(table("variacoes")["sku"].astype(str))
            preview = pd.DataFrame([{"SKU": row["sku"], "Produto": product_id, "Tamanho": row["size_id"], "Cor": row["color_id"], "Kit": row["kit"], "Material": row["material_id"], "Status": "JÁ CADASTRADO" if row["sku"] in existing else "NOVO"} for row in rows])
            st.dataframe(preview, use_container_width=True, hide_index=True)
            if st.button("Confirmar gravação do lote", key="save_batch"):
                result = error_message(lambda: add_variations(rows))
                if result is not False and result is not None:
                    st.success(f"{result} variação(ões) nova(s) inserida(s).")
                    st.rerun()


def catalog_page() -> None:
    st.title("Catálogo")
    frame = catalog()
    search = st.text_input("Buscar por nome ou SKU")
    filters = st.columns(5)
    for column, label in zip(filters, ["Categoria", "Produto", "Tamanho", "Cor", "Material"]):
        if label in frame:
            selected = column.multiselect(label, sorted(frame[label].dropna().unique()))
            if selected:
                frame = frame[frame[label].isin(selected)]
    active_filter = st.selectbox("Status", ["Todos", "Sim", "Nao"])
    if active_filter != "Todos":
        frame = frame[frame["Ativo"].astype(str) == active_filter]
    if search:
        mask = frame["SKU"].astype(str).str.contains(search, case=False, na=False) | frame["Produto"].astype(str).str.contains(search, case=False, na=False)
        frame = frame[mask]
    st.dataframe(frame, use_container_width=True, hide_index=True)


def auxiliary_page() -> None:
    st.title("Cadastros auxiliares")
    definitions = [("Categorias", "categorias"), ("Tamanhos", "tamanhos"), ("Cores", "cores"), ("Materiais", "materiais")]
    tabs = st.tabs([item[0] for item in definitions])
    for tab, (label, kind) in zip(tabs, definitions):
        with tab:
            with st.form(f"new_{kind}"):
                name = st.text_input("Nome", key=f"name_{kind}")
                abbreviation = st.text_input("Abreviação", key=f"abbr_{kind}")
                enabled = st.checkbox("Ativo", True, key=f"active_{kind}")
                submitted = st.form_submit_button("Cadastrar")
            if submitted:
                if error_message(lambda: add_domain(kind, name, abbreviation, enabled)) is not False:
                    st.success(f"{label} cadastrado com sucesso.")
                    st.rerun()
            st.dataframe(table(kind), use_container_width=True, hide_index=True)


try:
    page = st.sidebar.radio("Navegação", ["Dashboard", "Produtos", "Variações", "Catálogo", "Cadastros Auxiliares"])
    {"Dashboard": dashboard, "Produtos": products_page, "Variações": variations_page, "Catálogo": catalog_page, "Cadastros Auxiliares": auxiliary_page}[page]()
except SheetsError as exc:
    st.error(str(exc))
