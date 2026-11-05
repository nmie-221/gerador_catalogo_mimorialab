"""Single product screen: identification, recipe (cost), price, fiscal data and shipping.

All values live in session state under a per-product prefix, so adding recipe
lines, creating a raw material or switching tabs never loses what was typed.
Nothing is written until "Salvar produto"; the product and its recipe are then
saved together.
"""
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import streamlit as st

from repositories import fiscal, production as repo
from repositories.data import active, save_product, table
from services import dynamodb as store
from utils.pricing import decimal, quote
from utils.total_cost import estimate
from utils.validators import format_ncm
from views.production import PURCHASE_UNITS, USAGE_UNITS, money, suggested_input

DOMAINS = [("categoria", "categorias", "Categoria"), ("tamanho", "tamanhos", "Tamanho"), ("cor", "cores", "Cor/tema"),
           ("material", "materiais", "Material"), ("qtd_kit", "kits", "Kit")]
MEASURES = [("peso_liquido_g", "Peso líquido (g)", "Peso do produto sem a embalagem de envio."),
            ("peso_bruto_g", "Peso bruto (g)", "Peso do pacote pronto para envio, com embalagem."),
            ("altura_cm", "Altura do pacote (cm)", None), ("largura_cm", "Largura do pacote (cm)", None),
            ("comprimento_cm", "Comprimento do pacote (cm)", None)]


def _num(value, default=0.0):
    try:
        return float(decimal(value or 0))
    except ValueError:
        return default


def _key(fk, name):
    return f"{fk}_{name}"


def _reset(fk):
    for name in [k for k in st.session_state if str(k).startswith(fk + "_")]:
        del st.session_state[name]


def _add_row(fk, group, **values):
    rid = uuid4().hex[:8]
    st.session_state[_key(fk, group)] = [*st.session_state[_key(fk, group)], rid]
    for name, value in values.items():
        st.session_state[f"{fk}_{name}_{rid}"] = value
    return rid


def _remove_row(fk, group, rid):
    st.session_state[_key(fk, group)] = [r for r in st.session_state[_key(fk, group)] if r != rid]


def _load(fk, product, costs, config, fiscal_tables):
    """Copy the stored product and recipe into session state (once per edit)."""
    ss = st.session_state
    p = product or {}
    ss[_key(fk, "base")] = deepcopy(costs)
    ss[_key(fk, "name")] = str(p.get("nome_produto", ""))
    ss[_key(fk, "image")] = str(p.get("imagem_url", ""))
    for field, _, _ in DOMAINS:
        ss[_key(fk, field)] = str(p.get(field, "")) or None
    ss[_key(fk, "price")] = f"{_num(p.get('preco')):.2f}"
    ss[_key(fk, "minutes")] = _num(costs["minutes"])
    ss[_key(fk, "print_id")] = costs["print_id"] if any(x["id"] == costs["print_id"] for x in config["prints"]) else ""
    ss[_key(fk, "prints")] = int(costs["prints"])
    ss[_key(fk, "margin")] = _num(costs["margin"])
    for group in ["recipe", "extras", "platforms"]:
        ss[_key(fk, group)] = []
    for row in costs["recipe"]:
        _add_row(fk, "recipe", mat=row["material_id"], qty=_num(row["quantity"]))
    extras = list(costs.get("extras", []))
    if _num(costs["other"]):
        extras.append(dict(name="Outros custos", value=costs["other"]))
    if not repo.has_costs(costs) and _num(p.get("custo")):
        # Older products only had a typed cost: keep it as a recipe line so the
        # total stays the same and it is never counted twice.
        extras.append(dict(name="Custo informado anteriormente", value=p.get("custo")))
    for row in extras:
        _add_row(fk, "extras", xname=row["name"], xval=_num(row["value"]))
    for platform in costs["platforms"] or config.get("marketplace_defaults", []):
        _add_row(fk, "platforms", pname=platform["name"], pcom=_num(platform["commission"]),
                 pfix=_num(platform["fixed"]), pfre=_num(platform["freight"]))
    for kind, records in fiscal_tables.items():
        field = fiscal.KINDS[kind]["field"]
        ss[_key(fk, field)] = str(p.get(field, "") or "") or fiscal.default_code(records)
    for field, _, _ in MEASURES:
        ss[_key(fk, field)] = _num(p.get(field))
    ss[_key(fk, "on_demand")] = str(p.get("sob_encomenda", "")) == "Sim"
    ss[_key(fk, "days")] = int(_num(p.get("dias_producao")))
    ss[_key(fk, "loaded")] = True


def _collect_costs(fk):
    ss = st.session_state
    data = deepcopy(ss[_key(fk, "base")])
    data.update(
        recipe=[dict(material_id=ss[f"{fk}_mat_{r}"], quantity=ss[f"{fk}_qty_{r}"]) for r in ss[_key(fk, "recipe")] if ss.get(f"{fk}_mat_{r}")],
        minutes=ss[_key(fk, "minutes")], print_id=ss[_key(fk, "print_id")] or "", prints=ss[_key(fk, "prints")],
        other=0, margin=ss[_key(fk, "margin")],
        extras=[dict(name=ss[f"{fk}_xname_{r}"], value=ss[f"{fk}_xval_{r}"]) for r in ss[_key(fk, "extras")]],
        platforms=[dict(id=r, name=ss[f"{fk}_pname_{r}"].strip(), commission=ss[f"{fk}_pcom_{r}"], fixed=ss[f"{fk}_pfix_{r}"], freight=ss[f"{fk}_pfre_{r}"])
                   for r in ss[_key(fk, "platforms")]],
    )
    return data


def _collect_values(fk):
    ss = st.session_state
    values = dict(nome_produto=ss[_key(fk, "name")], imagem_url=ss[_key(fk, "image")], preco=ss[_key(fk, "price")],
                  sob_encomenda=ss[_key(fk, "on_demand")], dias_producao=ss[_key(fk, "days")])
    for field, _, _ in DOMAINS:
        values[field] = ss[_key(fk, field)]
    for spec in fiscal.KINDS.values():
        values[spec["field"]] = ss[_key(fk, spec["field"])]
    for field, _, _ in MEASURES:
        values[field] = ss[_key(fk, field)]
    return values


def _select(fk, field, label, options, names, help=None):
    """Selectbox bound to session state that tolerates values no longer offered."""
    key = _key(fk, field)
    current = st.session_state.get(key)
    if current and current not in options:
        options = [*options, current]
    if current not in options:
        st.session_state[key] = None
    return st.selectbox(label, options, key=key, format_func=lambda v: names.get(v, f"{v} (inativo)") if v else "— não informado —",
                        index=None, placeholder="Selecione", help=help)


def _identification(fk):
    st.text_input("Nome do produto", key=_key(fk, "name"))
    columns = st.columns(2)
    for index, (field, kind, label) in enumerate(DOMAINS):
        frame = active(kind)
        names = {str(r["id"]): f"{r['nome']} ({r['abreviacao']})" for _, r in frame.iterrows()}
        with columns[index % 2]:
            _select(fk, field, label, list(names), names)
    st.text_input("URL da imagem (opcional)", key=_key(fk, "image"))
    st.caption("O SKU é gerado automaticamente por categoria, tamanho, cor, kit e material.")


def _new_material_form(fk, items):
    with st.expander("➕ Cadastrar nova matéria-prima e já incluir na ficha"):
        with st.form(_key(fk, "new_material"), clear_on_submit=True):
            c1, c2 = st.columns(2)
            name = c1.text_input("Nome da matéria-prima")
            brand = c2.text_input("Marca")
            with c1:
                pack = suggested_input("Unidade de compra", PURCHASE_UNITS, [m["pack"] for m in items], "Pacote")
            with c2:
                unit = suggested_input("Unidade de uso", USAGE_UNITS, [m["unit"] for m in items], "unidade")
            per = c1.number_input("Quantidade de uso por embalagem", min_value=0.000001, value=1.0, format="%g")
            price = c2.number_input("Preço de uma embalagem (R$)", min_value=0.0, value=0.0)
            minimum = c1.number_input("Estoque mínimo (unidade de uso)", min_value=0.0, value=0.0)
            packs = c2.number_input("Embalagens que você já tem (opcional)", min_value=0.0, value=0.0)
            quantity = st.number_input("Consumo por produto (unidade de uso)", min_value=0.000001, value=1.0, format="%g")
            if st.form_submit_button("Cadastrar e incluir na ficha"):
                try:
                    material = repo.save_material(dict(name=name, brand=brand, pack=pack or "", per=per, unit=unit or "",
                                                       price=price, minimum=minimum, stock=0, active=True))
                    if packs:
                        repo.move(material["SK"], "Entrada de compra", packs, str(uuid4()), price, "Saldo inicial informado no cadastro do produto")
                except (store.StorageError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    _add_row(fk, "recipe", mat=material["SK"], qty=quantity)
                    st.session_state[_key(fk, "notice")] = f"Matéria-prima {material['name']} cadastrada e incluída na ficha."
                    st.rerun()


def _recipe(fk, items, config):
    ss = st.session_state
    known = {m["SK"]: m for m in items}
    st.markdown("**Matérias-primas por unidade**")
    selectable = [m["SK"] for m in items if m["active"]]
    for rid in ss[_key(fk, "recipe")]:
        c1, c2, c3, c4 = st.columns([3, 1.4, 1.2, .6], vertical_alignment="bottom")
        mat_key = f"{fk}_mat_{rid}"
        options = selectable + ([ss[mat_key]] if ss.get(mat_key) and ss[mat_key] not in selectable else [])
        if ss.get(mat_key) not in options:
            ss[mat_key] = None
        with c1:
            mid = st.selectbox("Matéria-prima", options, key=mat_key, index=None, placeholder="Selecione",
                               format_func=lambda i: f"{known[i]['name']} · {known[i]['brand']} ({known[i]['unit']})" if i in known else "Material não encontrado")
        m = known.get(mid)
        c2.number_input("Consumo" + (f" ({m['unit']})" if m else ""), min_value=0.000001, format="%g", key=f"{fk}_qty_{rid}")
        line = decimal(m["price"]) / decimal(m["per"], positive=True) * decimal(ss[f"{fk}_qty_{rid}"]) if m else 0
        c3.caption(f"{money(line)}")
        c4.button("✕", key=f"{fk}_rm_recipe_{rid}", help="Remover da ficha", on_click=_remove_row, args=(fk, "recipe", rid))
    if not selectable:
        st.info("Nenhuma matéria-prima ativa. Cadastre uma abaixo.")
    st.button("＋ Adicionar matéria-prima à ficha", key=_key(fk, "add_recipe"), on_click=_add_row,
              args=(fk, "recipe"), kwargs=dict(mat=None, qty=1.0), disabled=not selectable)
    _new_material_form(fk, items)

    st.markdown("**Mão de obra e impressão**")
    c1, c2, c3 = st.columns(3)
    c1.number_input("Tempo por unidade (minutos)", min_value=0.0, key=_key(fk, "minutes"),
                    help=f"Valor da hora atual: {money(repo.hourly(config))}. Altere em Custos de produção.")
    profiles = {"": "Sem impressão", **{p["id"]: p["name"] for p in config["prints"]}}
    c2.selectbox("Perfil de impressão", list(profiles), format_func=profiles.get, key=_key(fk, "print_id"))
    c3.number_input("Lados impressos por unidade", min_value=0, step=1, key=_key(fk, "prints"))

    st.markdown("**Outros custos por unidade**")
    st.caption("Ex.: embalagem de envio, brinde, etiqueta, terceirização. Use para custos que não são controlados em estoque.")
    for rid in ss[_key(fk, "extras")]:
        c1, c2, c3 = st.columns([3, 1.6, .6], vertical_alignment="bottom")
        c1.text_input("Descrição", key=f"{fk}_xname_{rid}")
        c2.number_input("Valor (R$)", min_value=0.0, format="%.2f", key=f"{fk}_xval_{rid}")
        c3.button("✕", key=f"{fk}_rm_extras_{rid}", help="Remover custo", on_click=_remove_row, args=(fk, "extras", rid))
    st.button("＋ Adicionar outro custo", key=_key(fk, "add_extra"), on_click=_add_row, args=(fk, "extras"), kwargs=dict(xname="", xval=0.0))


def _platforms(fk):
    ss = st.session_state
    st.markdown("**Plataformas de venda deste produto**")
    st.caption("Iniciadas com as taxas padrão de Custos de produção › Taxas das plataformas. Alterações aqui valem só para este produto.")
    for rid in ss[_key(fk, "platforms")]:
        c1, c2, c3, c4, c5 = st.columns([2, 1.2, 1.2, 1.2, .6], vertical_alignment="bottom")
        c1.text_input("Plataforma", key=f"{fk}_pname_{rid}")
        c2.number_input("Comissão (%)", min_value=0.0, max_value=99.99, key=f"{fk}_pcom_{rid}")
        c3.number_input("Tarifa fixa (R$)", min_value=0.0, key=f"{fk}_pfix_{rid}")
        c4.number_input("Frete (R$)", min_value=0.0, key=f"{fk}_pfre_{rid}")
        c5.button("✕", key=f"{fk}_rm_platforms_{rid}", help="Remover plataforma", on_click=_remove_row, args=(fk, "platforms", rid))
    st.button("＋ Adicionar plataforma", key=_key(fk, "add_platform"), on_click=_add_row, args=(fk, "platforms"),
              kwargs=dict(pname="", pcom=0.0, pfix=0.0, pfre=0.0))


def _use_price(fk, value):
    st.session_state[_key(fk, "price")] = f"{value:.2f}"


def _pricing(fk, production_cost, costs):
    _platforms(fk)
    st.number_input("Margem de lucro desejada (% sobre o preço)", min_value=0.0, max_value=99.0, key=_key(fk, "margin"))
    st.text_input("Preço de venda (R$)", key=_key(fk, "price"), help="Aceita 7,63 ou 7.63.")
    price = _num(st.session_state[_key(fk, "price")])
    rows, suggestions = [], []
    for platform in costs["platforms"]:
        if not platform["name"]:
            continue
        try:
            suggested = quote(production_cost, platform["commission"], platform["fixed"], platform["freight"], costs["margin"])["price"]
            current = estimate(0, price, production_cost, [platform])
        except ValueError as exc:
            st.error(f"{platform['name']}: {exc}")
            continue
        suggestions.append((platform["name"], suggested))
        rows.append({"Plataforma": platform["name"], "Comissão": money(current["commission"]), "Tarifa fixa": money(current["fixed"]),
                     "Frete": money(current["freight"]), "Custo total": money(current["total"]),
                     "Lucro no preço atual": money(current["profit"]), "Margem atual": f"{float(current['margin']):.1f}%",
                     f"Preço p/ {float(costs['margin']):g}% de margem": money(suggested)})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        columns = st.columns(len(suggestions) or 1)
        for column, (name, value) in zip(columns, suggestions):
            column.button(f"Usar preço {name}: {money(value)}", key=f"{fk}_use_{name}", on_click=_use_price, args=(fk, float(value)), width="stretch")
    else:
        st.info("Adicione ao menos uma plataforma para ver custo total, lucro e preço sugerido.")


def _fiscal(fk, fiscal_tables):
    st.caption("Dados usados pelos marketplaces e na emissão da nota fiscal. Cadastre novos códigos em Cadastros › Fiscal. Confirme os códigos com sua contabilidade.")
    category = st.session_state.get(_key(fk, "categoria"))
    categories = table("categorias")
    match = categories[categories["id"].astype(str) == str(category)]
    code = format_ncm(match.iloc[0]["ncm"]) if not match.empty else ""
    if code:
        st.text_input("NCM (da categoria)", value=code, disabled=True, key=f"{fk}_ncm_view_{category}")
    elif category:
        st.warning("A categoria escolhida não tem NCM. Informe-o em Cadastros › Categorias.")
    else:
        st.info("O NCM vem da categoria escolhida em Identificação.")
    columns = st.columns(2)
    for index, (kind, records) in enumerate(fiscal_tables.items()):
        spec = fiscal.KINDS[kind]
        names = {r["codigo"]: fiscal.label(kind, r) for r in records if r["ativo"]}
        with columns[index % 2]:
            _select(fk, spec["field"], spec["label"], ["", *names], names)


def _shipping(fk):
    st.caption("Medidas do pacote pronto para envio, como pedidas pelo Mercado Livre e pela Shopee.")
    columns = st.columns(2)
    for index, (field, label, help) in enumerate(MEASURES):
        columns[index % 2].number_input(label, min_value=0.0, step=1.0, format="%g", key=_key(fk, field), help=help)
    on_demand = st.checkbox("Produto feito sob encomenda", key=_key(fk, "on_demand"))
    st.number_input("Dias de produção", min_value=0, step=1, key=_key(fk, "days"), disabled=not on_demand,
                    help="Prazo informado ao marketplace para produtos por encomenda.")


def product_editor(product=None):
    """Render the single product screen. `product` is a catalog row dict or None for a new product."""
    pid = str(product["id_produto"]) if product else None
    fk = f"pedit_{pid}" if pid else "pnew"
    ss = st.session_state
    if notice := ss.pop(_key(fk, "notice"), None):
        st.success(notice)
    config = repo.settings()
    items = repo.materials()
    fiscal_tables = {kind: fiscal.items(kind) for kind in fiscal.KINDS}
    if not ss.get(_key(fk, "loaded")):
        _load(fk, product, repo.product_costs(pid) if pid else repo.empty_costs(None), config, fiscal_tables)

    tabs = st.tabs(["Identificação", "Ficha técnica (custo)", "Preço e plataformas", "Fiscal", "Envio e prazo"])
    with tabs[0]:
        _identification(fk)
    with tabs[1]:
        _recipe(fk, items, config)
    costs = _collect_costs(fk)
    try:
        parts = repo.breakdown(costs, config, items)
    except ValueError as exc:
        st.error(str(exc))
        parts = dict(materials=Decimal(0), labor=Decimal(0), printing=Decimal(0), other=Decimal(0), total=Decimal(0))
    with tabs[2]:
        _pricing(fk, parts["total"], costs)
    with tabs[3]:
        _fiscal(fk, fiscal_tables)
    with tabs[4]:
        _shipping(fk)

    with st.container(border=True, key=f"card_summary_{fk}"):
        st.subheader("Resumo do custo")
        cols = st.columns(5)
        for column, (label, value) in zip(cols, [("Materiais", parts["materials"]), ("Mão de obra", parts["labor"]), ("Impressão", parts["printing"]),
                                                  ("Outros", parts["other"]), ("Custo de produção", parts["total"])]):
            column.metric(label, money(value))
        price = _num(ss[_key(fk, "price")])
        valid = [p for p in costs["platforms"] if p["name"]]
        try:
            worst = estimate(0, price, parts["total"], valid)
        except ValueError:
            worst = None
        if worst and valid:
            st.caption(f"Pior cenário ({worst['platform']}): custo total {money(worst['total'])} · lucro {money(worst['profit'])} · margem {float(worst['margin']):.1f}% no preço {money(price)}.")
        save, discard = st.columns([2, 1])
        if save.button("💾 Salvar produto", type="primary", key=_key(fk, "save"), width="stretch"):
            try:
                new_id, sku = save_product(pid, _collect_values(fk), costs)
            except (store.StorageError, ValueError, KeyError) as exc:
                st.error(str(exc))
            else:
                _reset(fk)
                ss[_key(fk, "notice")] = f"Produto {'atualizado' if pid else 'cadastrado'}: {new_id} · SKU {sku}"
                st.rerun()
        discard.button("Descartar alterações", key=_key(fk, "discard"), on_click=_reset, args=(fk,), width="stretch")
