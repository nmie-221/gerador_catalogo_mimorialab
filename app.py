from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from repositories.data import active, add_domain, add_product, catalog, delete_domain, delete_product, edit_domain, edit_product, table
from services.auth import is_authenticated, login_screen, logout
from services.google_sheets import SheetsError
from utils.validators import number, required_fields

st.set_page_config(page_title="Catálogo de Produtos", page_icon="📦", layout="wide")
st.markdown(
    """
    <style>
    :root {
        --brand-purple: #7344B1;
        --brand-purple-light: #AF84E5;
        --brand-lilac: #F3EDFC;
        --brand-dark: #2D1D41;
        --brand-gold: #CC9D39;
    }
    div.stButton > button[kind="primary"],
    div.stFormSubmitButton > button,
    button[data-testid="baseButton-primary"] {
        background-color: var(--brand-purple) !important;
        border-color: var(--brand-purple) !important;
        color: white !important;
    }
    div.stButton > button[kind="primary"]:hover,
    div.stFormSubmitButton > button:hover,
    button[data-testid="baseButton-primary"]:hover {
        background-color: var(--brand-purple-light) !important;
        border-color: var(--brand-purple-light) !important;
    }
    input, textarea, select, [role="combobox"] {
        accent-color: var(--brand-purple) !important;
    }
    input:focus, textarea:focus, [data-baseweb="select"]:focus-within,
    [data-baseweb="input"]:focus-within, [data-baseweb="textarea"]:focus-within {
        border-color: var(--brand-purple-light) !important;
        box-shadow: 0 0 0 1px var(--brand-purple-light) !important;
    }
    [data-baseweb="tag"] {
        background-color: var(--brand-purple) !important;
    }
    [data-testid="stCheckbox"],
    [data-testid="stCheckbox"] *,
    [data-testid="stCheckbox"] label,
    [data-testid="stCheckbox"] label > div,
    [data-testid="stCheckbox"] label > div > div,
    [data-testid="stCheckbox"] [aria-selected="true"] {
        background-color: transparent !important;
        color: var(--brand-lilac) !important;
    }
    [data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"],
    [data-testid="stCheckbox"] input:checked + div {
        background-color: var(--brand-purple) !important;
        border-color: var(--brand-purple) !important;
    }
    [data-testid="stCheckbox"] svg,
    [data-testid="stCheckbox"] svg path {
        color: var(--brand-purple) !important;
        fill: var(--brand-purple) !important;
    }
    [data-baseweb="tab-highlight"] {
        background-color: var(--brand-purple-light) !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        color: var(--brand-purple-light) !important;
        background-color: transparent !important;
    }
    a, [data-testid="stMetricValue"] {
        color: var(--brand-purple-light) !important;
    }
    [data-testid="stProgressBar"] > div > div {
        background-color: var(--brand-purple) !important;
    }
    @media (max-width: 640px) {
        .stMainBlockContainer, .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            padding-top: 2rem;
        }
        h1 {
            font-size: 1.75rem !important;
        }
        .stButton > button, .stFormSubmitButton > button {
            min-height: 2.75rem;
        }
        [data-baseweb="tab-list"] {
            gap: 1rem;
            overflow-x: auto;
        }
        [data-baseweb="tab"] {
            flex-shrink: 0;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def product_form(values: dict | None = None, form_key: str = "new_product", before_pricing=None) -> tuple:
    values = values or {}
    def decimal_text(value: object) -> str:
        try:
            return f"{float(str(value or 0).replace(',', '.')):.2f}"
        except ValueError:
            return "0.00"

    categories, sizes, colors, materials, kits = (active(kind) for kind in ("categorias", "tamanhos", "cores", "materiais", "kits"))
    if before_pricing:
        characteristics_tab, simulation_tab, pricing_tab = st.tabs(["Características", "Simulação", "Preço e dados finais"])
    else:
        characteristics_tab = simulation_tab = pricing_tab = st.container()

    with characteristics_tab:
        st.subheader("Características do produto")
        name = st.text_input("Nome do produto", value=str(values.get("nome_produto", "")), key=f"{form_key}_name")
        category = domain_select(categories, "Categoria", f"{form_key}_category", values.get("categoria"))
        size = domain_select(sizes, "Tamanho", f"{form_key}_size", values.get("tamanho"))
        color = domain_select(colors, "Cor/tema", f"{form_key}_color", values.get("cor"))
        material = domain_select(materials, "Material", f"{form_key}_material", values.get("material"))
        kit = domain_select(kits, "Kit", f"{form_key}_kit", values.get("qtd_kit"))
    with simulation_tab:
        if before_pricing:
            before_pricing()
    with pricing_tab:
        st.subheader("Preço e dados finais")
        with st.form(form_key):
            st.caption("Informe valores decimais usando ponto, por exemplo: 7.63")
            price = st.text_input("Preço", value=decimal_text(values.get("preco", st.session_state.get(f"{form_key}_price", 0))), key=f"{form_key}_price")
            cost = st.text_input("Custo", value=decimal_text(values.get("custo", st.session_state.get(f"{form_key}_cost", 0))), key=f"{form_key}_cost")
            barcode = st.text_input("Código de barras (opcional)", value=str(values.get("codigo_barras", "")))
            image_url = st.text_input("URL da imagem (opcional)", value=str(values.get("imagem_url", "")))
            submitted = st.form_submit_button("Salvar")
    return submitted, name, category, size, color, material, price, cost, kit, barcode, image_url


def marketplace_simulator() -> None:
    simulation_fields = st.columns(4)
    cost_text = simulation_fields[0].text_input("Custo (R$)", value="0.00", key="new_marketplace_cost")
    margin_text = simulation_fields[1].text_input("Margem de lucro (%)", value="30.00", key="new_marketplace_margin")
    mercado_livre_fee_text = simulation_fields[2].text_input("Taxa Mercado Livre (%)", value="20.00", key="new_mercado_livre_fee")
    shopee_fee_text = simulation_fields[3].text_input("Taxa Shopee (%)", value="14.00", key="new_shopee_fee")

    def parse_simulation_value(value: str) -> float:
        try:
            parsed = float(value)
            return max(parsed, 0.0)
        except ValueError:
            return 0.0

    cost = parse_simulation_value(cost_text)
    profit_margin = parse_simulation_value(margin_text)
    mercado_livre_fee = min(parse_simulation_value(mercado_livre_fee_text), 99.99)
    shopee_fee = min(parse_simulation_value(shopee_fee_text), 99.99)
    base_price = cost * (1 + profit_margin / 100)
    mercado_livre_price = base_price / (1 - mercado_livre_fee / 100)
    shopee_price = base_price / (1 - shopee_fee / 100)
    result_columns = st.columns(2)
    result_columns[0].metric("Preço sugerido Mercado Livre", f"R$ {mercado_livre_price:.2f}")
    result_columns[1].metric("Preço sugerido Shopee", f"R$ {shopee_price:.2f}")
    action_columns = st.columns(2)
    if action_columns[0].button("Usar preço Mercado Livre", key="use_mercado_livre_price", use_container_width=True):
        st.session_state["new_product_price"] = f"{mercado_livre_price:.2f}"
        st.session_state["new_product_cost"] = f"{cost:.2f}"
        st.rerun()
    if action_columns[1].button("Usar preço Shopee", key="use_shopee_price", use_container_width=True):
        st.session_state["new_product_price"] = f"{shopee_price:.2f}"
        st.session_state["new_product_cost"] = f"{cost:.2f}"
        st.rerun()
    st.caption("Use um dos valores sugeridos no campo Preço abaixo, se desejar.")


def register_page() -> None:
    st.title("📝 Cadastrar produto")
    st.caption("✨ O SKU é gerado automaticamente por categoria, tamanho, cor, kit e material.")
    submitted, name, category, size, color, material, price, cost, kit, barcode, image_url = product_form(before_pricing=marketplace_simulator)
    if submitted:
        missing = required_fields({
            "Nome do produto": name,
            "Categoria": category,
            "Tamanho": size,
            "Cor/tema": color,
            "Material": material,
            "Kit": kit,
            "Preço": price,
            "Custo": cost,
        })
        if missing:
            st.error(f"Preencha os campos obrigatórios: {', '.join(missing)}.")
            return
        result = run(lambda: add_product(name, category, size, color, material, number(price, "O preco"), number(cost, "O custo"), kit, barcode, image_url))
        if result is not False:
            st.success(f"Produto cadastrado. SKU: {result}")
            st.rerun()


def query_page() -> None:
    st.title("🔎 Consultar produtos")
    products = catalog()
    if products.empty:
        st.info("📦 Nenhum produto cadastrado.")
        return
    search = st.text_input("Buscar por nome, SKU, código de barras ou ID")
    filters = st.columns(5)
    filter_columns = [
        ("Categoria", "Categoria"),
        ("Tamanho", "Tamanho"),
        ("Cor", "Cor"),
        ("Material", "Material"),
        ("Kit", "Kit"),
    ]
    for column, (label, field) in zip(filters, filter_columns):
        options = sorted(products[field].dropna().astype(str).unique())
        selected = column.multiselect(label, options, key=f"dashboard_filter_{field}")
        if selected:
            products = products[products[field].astype(str).isin(selected)]
    if search:
        mask = products.astype(str).apply(lambda column: column.str.contains(search, case=False, na=False)).any(axis=1)
        products = products[mask]
    st.dataframe(
        products,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Preco": st.column_config.NumberColumn("Preço", format="R$ %.2f"),
            "Custo": st.column_config.NumberColumn("Custo", format="R$ %.2f"),
            "Lucro": st.column_config.NumberColumn("Lucro", format="R$ %.2f"),
            "Margem %": st.column_config.NumberColumn("Margem %", format="%.2f%%"),
            "imagem_url": st.column_config.ImageColumn("Imagem", help="Imagem cadastrada pela URL"),
        },
    )


def manage_page() -> None:
    st.title("⚙️ Gerenciar produtos")
    products = table("produtos")
    if products.empty:
        st.info("Nenhum produto cadastrado.")
        return
    edit_tab, delete_tab = st.tabs(["✏️ Editar produto", "🗑️ Excluir produto"])
    options = {f"{row.nome_produto} ({row.id_produto})": row.id_produto for row in products.itertuples()}
    with edit_tab:
        selected_label = st.selectbox("Produto para editar", list(options), key="edit_selected_product")
        selected_id = options[selected_label]
        selected = products[products["id_produto"].astype(str) == str(selected_id)].iloc[0].to_dict()
        submitted, name, category, size, color, material, price, cost, kit, barcode, image_url = product_form(selected, "edit_product")
        if submitted:
            missing = required_fields({
                "Nome do produto": name,
                "Categoria": category,
                "Tamanho": size,
                "Cor/tema": color,
                "Material": material,
                "Kit": kit,
                "Preço": price,
                "Custo": cost,
            })
            if missing:
                st.error(f"Preencha os campos obrigatórios: {', '.join(missing)}.")
                return
            result = run(lambda: edit_product(selected_id, name, category, size, color, material, number(price, "O preco"), number(cost, "O custo"), kit, barcode, image_url))
            if result is not False:
                st.success(f"Produto atualizado. SKU: {result}")
                st.rerun()
    with delete_tab:
        selected_label = st.selectbox("Produto para excluir", list(options), key="delete_selected_product")
        selected_id = options[selected_label]
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
    st.title("🧩 Cadastros auxiliares")
    definitions = [("Categorias", "categorias"), ("Tamanhos", "tamanhos"), ("Cores", "cores"), ("Materiais", "materiais"), ("Kits", "kits")]
    tabs = st.tabs([label for label, _ in definitions])
    for tab, (label, kind) in zip(tabs, definitions):
        with tab:
            notice = st.session_state.pop(f"notice_{kind}", None)
            if notice:
                st.success(notice)
            with st.form(f"new_{kind}"):
                name = st.text_input("Nome", key=f"{kind}_name")
                abbrev = st.text_input("Abreviação", key=f"{kind}_abbrev")
                enabled = st.checkbox("Ativo", True, key=f"{kind}_active")
                submitted = st.form_submit_button("Cadastrar")
            if submitted:
                if run(lambda: add_domain(kind, name, abbrev, enabled)) is not False:
                    st.success(f"{label} cadastrado.")
                    st.rerun()
            frame = table(kind)
            st.dataframe(frame, use_container_width=True, hide_index=True)
            if frame.empty:
                st.info("Cadastre um item para poder editar ou excluir.")
                continue
            with st.expander("✏️ Alterar ou excluir um item"):
                identifier = st.selectbox(
                    "Selecione o item", frame["id"].astype(str).tolist(),
                    format_func=lambda value, data=frame: f"{data.loc[data['id'].astype(str) == value, 'nome'].iloc[0]} ({value})",
                    key=f"{kind}_selected",
                )
                selected = frame.loc[frame["id"].astype(str) == identifier].iloc[0]
                item_key = f"{kind}_{identifier}"
                st.caption("Itens vinculados a produtos podem ser desativados. A abreviação desses itens é preservada para manter os SKUs existentes.")
                with st.form(f"edit_{item_key}"):
                    edited_name = st.text_input("Nome", value=str(selected["nome"]), key=f"edit_name_{item_key}")
                    edited_abbrev = st.text_input("Abreviação", value=str(selected["abreviacao"]), key=f"edit_abbrev_{item_key}")
                    edited_enabled = st.checkbox("Ativo", value=str(selected["ativo"]).casefold() in ["sim", "true", "1"], key=f"edit_active_{item_key}")
                    save = st.form_submit_button("Salvar alterações")
                if save:
                    if run(lambda: edit_domain(kind, identifier, edited_name, edited_abbrev, edited_enabled)) is not False:
                        st.session_state[f"notice_{kind}"] = "Item atualizado."
                        st.rerun()
                st.warning(f"Excluir remove permanentemente o item {selected['nome']} ({identifier}).")
                with st.form(f"delete_{item_key}"):
                    confirmed = st.checkbox("Confirmo a exclusão deste item", key=f"confirm_{item_key}")
                    remove = st.form_submit_button("Excluir item")
                if remove:
                    if not confirmed:
                        st.error("Confirme a exclusão antes de continuar.")
                    elif run(lambda: delete_domain(kind, identifier)) is not False:
                        st.session_state[f"notice_{kind}"] = "Item excluído."
                        st.rerun()


def dashboard() -> None:
    query_page()


if not is_authenticated():
    login_screen()
    st.stop()

with st.container(border=True):
    logo_path = Path(__file__).parent / "assets" / "logo.png"
    if logo_path.exists():
        st.image(str(logo_path), width=90)
    else:
        st.subheader("📦 Catálogo MimoriaLab")
    st.button("🚪 Sair", on_click=logout, key="logout")

navigation_pages = ["🔎 Consultar Produtos", "📝 Cadastrar produto", "⚙️ Editar ou excluir", "🧩 Catálogos auxiliares"]
if st.session_state.get("page") == "Dashboard":
    st.session_state.page = "🔎 Consultar Produtos"
if st.session_state.get("page") not in navigation_pages:
    st.session_state.page = "🔎 Consultar Produtos"
st.selectbox("O que você quer fazer?", navigation_pages, key="page")
page = st.session_state.page
try:
    {
        "🔎 Consultar Produtos": dashboard,
        "📝 Cadastrar produto": register_page,
        "⚙️ Editar ou excluir": manage_page,
        "🧩 Catálogos auxiliares": auxiliary_page,
    }[page]()
except SheetsError as exc:
    st.error(str(exc))
