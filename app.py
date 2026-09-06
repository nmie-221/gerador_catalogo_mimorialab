from __future__ import annotations

import pandas as pd
import streamlit as st

from repositories.data import active, add_domain, add_product, build_product_sku, catalog, delete_product, edit_product, table
from services.auth import is_authenticated, login_screen, logout
from services.google_sheets import SheetsError

st.set_page_config(page_title="Catálogo de Produtos", page_icon="📦", layout="wide")


def run(action):
    try:
        return action()
    except (SheetsError, ValueError, KeyError) as exc:
        st.error(str(exc))
        return False


def domain_select(frame: pd.DataFrame, label: str, key: str, selected_id: str | None = None) -> str | None:
    if frame.empty:
        st.warning(f"Nenhum registro ativo disponível para {label.lower()}.")
        return None
    options = {f"{row['nome']} ({row['id']})": row["id"] for _, row in frame.iterrows()}
    labels = list(options)
    default_index = 0
    if selected_id in options.values():
        default_index = list(options.values()).index(selected_id)
    selected = st.selectbox(label, labels, index=default_index, key=key)
    return options[selected]


def product_form(values: dict | None = None, form_key: str = "new_product") -> tuple:
    values = values or {}
    categories, sizes, colors, materials, kits = (active(kind) for kind in ("categorias", "tamanhos", "cores", "materiais", "kits"))
    with st.form(form_key):
        name = st.text_input("Nome do produto", value=str(values.get("nome_produto", "")))
        category = domain_select(categories, "Categoria", f"{form_key}_category", values.get("categoria"))
        size = domain_select(sizes, "Tamanho", f"{form_key}_size", values.get("tamanho"))
        color = domain_select(colors, "Cor/tema", f"{form_key}_color", values.get("cor"))
        material = domain_select(materials, "Material", f"{form_key}_material", values.get("material"))
        kit = domain_select(kits, "Kit", f"{form_key}_kit", values.get("qtd_kit"))
        price = st.number_input("Preço", min_value=0.0, value=float(values.get("preco", 0) or 0), step=0.01, key=f"{form_key}_price")
        cost = st.number_input("Custo", min_value=0.0, value=float(values.get("custo", 0) or 0), step=0.01, key=f"{form_key}_cost")
        barcode = st.text_input("Código de barras", value=str(values.get("codigo_barras", "")))
        submitted = st.form_submit_button("Salvar")
    return submitted, name, category, size, color, material, price, cost, kit, barcode


def products_page() -> None:
    st.title("Produtos")
    st.caption("O SKU é gerado automaticamente por categoria, tamanho, cor, kit e material.")
    submitted, name, category, size, color, material, price, cost, kit, barcode = product_form()
    if submitted and all([category, size, color, material, kit]):
        result = run(lambda: add_product(name, category, size, color, material, price, cost, kit, barcode))
        if result is not False:
            st.success(f"Produto cadastrado. SKU: {result}")
            st.rerun()
    products = table("produtos")
    st.dataframe(catalog(), use_container_width=True, hide_index=True)
    if products.empty:
        return
    options = {f"{row.nome_produto} ({row.id_produto})": row.id_produto for row in products.itertuples()}
    selected_label = st.selectbox("Produto para editar ou excluir", list(options), key="selected_product")
    selected_id = options[selected_label]
    selected = products[products["id_produto"].astype(str) == str(selected_id)].iloc[0].to_dict()
    with st.expander("Editar produto"):
        submitted, name, category, size, color, material, price, cost, kit, barcode = product_form(selected, "edit_product")
        if submitted and all([category, size, color, material, kit]):
            result = run(lambda: edit_product(selected_id, name, category, size, color, material, price, cost, kit, barcode))
            if result is not False:
                st.success(f"Produto atualizado. SKU: {result}")
                st.rerun()
    st.warning("A exclusão remove a linha do cadastro PRODUTOS.")
    if st.button("Excluir produto", type="secondary"):
        st.session_state.confirm_delete = selected_id
    if st.session_state.get("confirm_delete") == selected_id:
        if st.button("Confirmar exclusão", key="confirm_delete_product"):
            result = run(lambda: delete_product(selected_id))
            if result is not False:
                st.success("Produto excluído.")
                st.session_state.pop("confirm_delete", None)
                st.rerun()


def auxiliary_page() -> None:
    st.title("Cadastros auxiliares")
    definitions = [("Categorias", "categorias"), ("Tamanhos", "tamanhos"), ("Cores", "cores"), ("Materiais", "materiais"), ("Kits", "kits")]
    tabs = st.tabs([label for label, _ in definitions])
    for tab, (label, kind) in zip(tabs, definitions):
        with tab:
            with st.form(f"new_{kind}"):
                name = st.text_input("Nome", key=f"{kind}_name")
                abbrev = st.text_input("Abreviação", key=f"{kind}_abbrev")
                enabled = st.checkbox("Ativo", True, key=f"{kind}_active")
                submitted = st.form_submit_button("Cadastrar")
            if submitted:
                if run(lambda: add_domain(kind, name, abbrev, enabled)) is not False:
                    st.success(f"{label} cadastrado.")
                    st.rerun()
            st.dataframe(table(kind), use_container_width=True, hide_index=True)


def dashboard() -> None:
    st.title("Dashboard")
    products = table("produtos")
    domains = [len(active(kind)) for kind in ("categorias", "tamanhos", "cores", "materiais", "kits")]
    cols = st.columns(4)
    for col, label, value in zip(cols, ["Produtos", "Categorias", "SKUs", "Kits"], [len(products), domains[0], products["sku"].nunique() if not products.empty else 0, domains[4]]):
        col.metric(label, value)
    st.dataframe(catalog().tail(10), use_container_width=True, hide_index=True)


if not is_authenticated():
    login_screen()
    st.stop()

st.sidebar.button("Sair", on_click=logout)
page = st.sidebar.selectbox("Navegação", ["Dashboard", "Produtos", "Catálogos auxiliares"])
try:
    {"Dashboard": dashboard, "Produtos": products_page, "Catálogos auxiliares": auxiliary_page}[page]()
except SheetsError as exc:
    st.error(str(exc))
