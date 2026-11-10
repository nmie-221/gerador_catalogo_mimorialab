"""Native Streamlit screens backed by the production repository."""
from copy import deepcopy
from uuid import uuid4

import pandas as pd
import streamlit as st

from repositories import production as repo
from repositories.data import table
from services import dynamodb as store


def money(value):
    return f'R$ {float(value):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def finish(message):
    st.session_state['production_notice'] = message
    st.rerun()


def notice():
    if value := st.session_state.pop('production_notice', None):
        st.success(value)


def action(fn, message):
    try:
        fn()
    except (store.StorageError, ValueError) as exc:
        st.error(str(exc))
    else:
        finish(message)


def n(label, value=0, **kwargs):
    return st.number_input(label, min_value=0., value=float(value), **kwargs)


def costs_page():
    st.caption('CONFIGURAÇÃO DE CUSTOS')
    st.title('Custos de produção')
    notice()
    config = repo.settings()
    section = st.selectbox('Configuração', ['Hora de mão de obra', 'Custo por impressão', 'Taxas das plataformas'], key='costs_section')
    if section == 'Hora de mão de obra':
        if 'costs_hour_mode' not in st.session_state:
            st.session_state.costs_hour_mode = 'Informar valor da hora' if config['hour_mode'] == 'direct' else 'Calcular pela remuneração mensal'
        mode = st.radio('Como definir o valor?', ['Informar valor da hora', 'Calcular pela remuneração mensal'], key='costs_hour_mode')
        with st.form(f"hour_settings_{config['revision']}"):
            data = deepcopy(config)
            if mode == 'Informar valor da hora':
                data['hour_mode'] = 'direct'
                data['hourly'] = n('Valor da hora (R$)', config['hourly'])
            else:
                data['hour_mode'] = 'monthly'
                data['monthly'] = n('Remuneração mensal desejada (R$)', config['monthly'])
                data['hours'] = st.number_input('Horas produtivas por mês', min_value=.01, value=float(config['hours']))
            if st.form_submit_button('Salvar valor da hora'):
                action(lambda: repo.save_settings(data), 'Valor da hora salvo.')
        st.metric('Valor da hora cadastrado', money(repo.hourly(config)))
        st.info('Na ficha técnica, informe o tempo de produção por unidade em minutos.')
    elif section == 'Taxas das plataformas':
        st.subheader('Taxas padrão para novos produtos')
        st.caption('Os valores são editáveis e servem como referência inicial. Confira as tarifas vigentes na plataforma antes de precificar.')
        defaults = config.get('marketplace_defaults', [])
        by_name = {p['name']: p for p in defaults}
        names = list(dict.fromkeys(['Mercado Livre', 'Shopee'] + list(by_name)))
        with st.form(f"marketplace_defaults_{config['revision']}"):
            updated_platforms = []
            for name in names:
                current = by_name.get(name, {})
                with st.expander(name, expanded=True):
                    cols = st.columns(3)
                    commission = cols[0].number_input('Comissão (%)', min_value=0., max_value=99.99, value=float(current.get('commission', 0)), key='default_commission_'+name)
                    fixed = cols[1].number_input('Tarifa fixa (R$)', min_value=0., value=float(current.get('fixed', 0)), key='default_fixed_'+name)
                    freight = cols[2].number_input('Frete reservado (R$)', min_value=0., value=float(current.get('freight', 0)), key='default_freight_'+name)
                    updated_platforms.append(dict(name=name, commission=commission, fixed=fixed, freight=freight))
            if st.form_submit_button('Salvar taxas padrão'):
                updated = deepcopy(config)
                updated['marketplace_defaults'] = updated_platforms
                action(lambda: repo.save_settings(updated), 'Taxas padrão salvas.')
        st.info('As tarifas variáveis por faixa de preço devem ser conferidas antes de aplicar o preço. As taxas padrão não alteram fichas já cadastradas.')
    else:
        profiles = config['prints']
        identifiers = ['new']+[p['id'] for p in profiles]
        identifier = st.selectbox('Perfil de impressão', identifiers, format_func=lambda i: 'Novo perfil' if i == 'new' else next(p['name'] for p in profiles if p['id'] == i))
        profile = next((p for p in profiles if p['id'] == identifier), dict(id=uuid4().hex, name='', ink=0, **{'yield': 1}, maintenance=0, energy=0))
        with st.form(f"print_profile_{identifier}_{config['revision']}"):
            data = deepcopy(profile)
            data['name'] = st.text_input('Nome do perfil / impressora', profile['name'])
            data['ink'] = n('Custo do conjunto de tinta ou toner (R$)', profile['ink'])
            data['yield'] = st.number_input('Rendimento estimado em lados impressos', min_value=1, value=int(profile['yield']))
            data['maintenance'] = n('Manutenção por lado (R$)', profile['maintenance'], step=.001, format='%.3f')
            data['energy'] = n('Energia por lado (R$)', profile['energy'], step=.001, format='%.3f')
            if st.form_submit_button('Salvar perfil'):
                updated = deepcopy(config)
                updated['prints'] = [data if p['id'] == identifier else p for p in profiles] if identifier != 'new' else profiles+[data]
                action(lambda: repo.save_settings(updated), 'Perfil de impressão salvo.')
        if identifier != 'new':
            st.metric('Custo por lado impresso', money(repo.print_rate(profile)))
        st.info('Papel entra como matéria-prima na ficha. Frente e verso correspondem a dois lados. Rendimento de tinta é estimado.')


def suggested_input(label, defaults, existing=(), current=None):
    options, seen = [], set()
    for value in [*defaults, *existing, *([current] if current else [])]:
        text = str(value).strip()
        if text and text.casefold() not in seen:
            options.append(text)
            seen.add(text.casefold())
    selected = next((i for i, value in enumerate(options) if current and value.casefold() == str(current).casefold()), None)
    return st.selectbox(label, options, index=selected, accept_new_options=True,
                        placeholder='Selecione ou digite uma nova opção')


def cost_fields(m=None, key=''):
    """Choose how the cost per unit of use is defined (inside a form)."""
    m = m or {}
    modes = list(repo.COST_MODES)
    mode = st.radio('Custo por unidade de uso', modes, format_func=repo.COST_MODES.get, horizontal=True,
                    index=modes.index(m.get('cost_mode') or 'pack'), key=f'cost_mode_{key}')
    unit_price = st.number_input('Preço por unidade de uso (R$)', min_value=0., value=float(m.get('unit_price') or 0),
                                 step=.01, format='%.4f', key=f'unit_price_{key}',
                                 help='Usado somente na opção "Informar o preço por unidade de uso". Não é recalculado nas entradas de compra.')
    return mode, unit_price


PURCHASE_UNITS = ['Resma', 'Metro', 'Cm', 'Pacote', 'Rolo', 'Caixa', 'Folha', 'Unidade', 'Frasco', 'Pote', 'Litro', 'Quilo']
USAGE_UNITS = ['folha', 'unidade', 'Resma', 'Metro', 'Cm', 'm²', 'grama', 'quilo', 'mililitro', 'litro']


def inventory_page():
    st.caption('SUPRIMENTOS')
    st.title('Matérias-primas')
    st.caption('Compra, marca, custo por uso e saldo em um só lugar.')
    notice()
    items = repo.materials()
    sections = ['Saldo e custos', 'Cadastrar matéria-prima', 'Editar matéria-prima', 'Registrar entrada', 'Perda ou ajuste', 'Histórico']
    if st.session_state.get('_inventory_section') not in sections:
        st.session_state._inventory_section = sections[0]
    if st.session_state.get('inventory_section') not in sections:
        st.session_state.inventory_section = st.session_state._inventory_section

    def select_inventory_section():
        if st.session_state.inventory_section is None:
            st.session_state.inventory_section = st.session_state._inventory_section
        st.session_state._inventory_section = st.session_state.inventory_section

    with st.container(key='stock_nav'):
        st.pills('Área de estoque', sections, selection_mode='single', key='inventory_section',
                 on_change=select_inventory_section, label_visibility='collapsed')
    section = st.session_state._inventory_section
    if section == 'Cadastrar matéria-prima':
        with st.form('new_material', clear_on_submit=False):
            data = dict(
                name=st.text_input('Nome'),
                brand=st.text_input('Marca'),
                pack=suggested_input('Unidade de compra', PURCHASE_UNITS, [m['pack'] for m in items], 'Resma'),
                per=st.number_input('Quantidade de uso por embalagem', min_value=0.000001, value=500., step=1., format='%g'),
                unit=suggested_input('Unidade de uso', USAGE_UNITS, [m['unit'] for m in items], 'folha'),
                price=n('Preço de uma embalagem (R$)'), minimum=n('Estoque mínimo na unidade de uso'), stock=0, active=True,
            )
            data['cost_mode'], data['unit_price'] = cost_fields(key='new')
            st.caption('Você pode selecionar uma sugestão ou digitar um novo valor. Preço e estoque mínimo continuam livres.')
            if st.form_submit_button('Salvar matéria-prima'):
                action(lambda: repo.save_material(data), 'Matéria-prima cadastrada. Registre uma entrada para adicionar estoque.')
        return
    if section == 'Histórico':
        events = store.query(repo.EVENTS)
        for event in sorted(events, key=lambda e: e['date'], reverse=True):
            with st.expander(event['date'][:19].replace('T', ' ')+' UTC · '+event['type']):
                st.write({k: v for k, v in event.items() if k not in ['PK', 'SK']})
        if not events:
            st.info('Ainda não há movimentações.')
        return
    if not items:
        st.info('Cadastre sua primeira matéria-prima. Os dados desta área são salvos na base de dados.')
        return
    if section == 'Saldo e custos':
        search = st.text_input('Buscar material ou marca')
        total = sum(float(m['stock'])*float(repo.unit_cost(m)) for m in items)
        st.metric('Valor estimado em estoque', money(total))
        st.caption('Estimativa pelo último preço de compra. Não é custo médio contábil.')
        for m in items:
            if search.casefold() not in (m['name']+' '+m['brand']).casefold():
                continue
            with st.container(border=True, key="card_material_"+m["SK"]):
                st.subheader(m['name'])
                st.caption(m['brand']+' · '+('Ativo' if m['active'] else 'Inativo'))
                st.write(f"Saldo: **{float(m['stock']):g} {m['unit']}** · Custo por uso: **{money(repo.unit_cost(m))}**"+(' (informado)' if m.get('cost_mode') == 'unit' else ''))
                if m['active'] and m['stock'] <= m['minimum']:
                    st.warning(f"Repor estoque. Mínimo: {float(m['minimum']):g} {m['unit']}")
        return
    options = items if section == 'Editar matéria-prima' else [m for m in items if m['active']]
    if not options:
        st.info('Ative uma matéria-prima para registrar movimentações.')
        return
    identifier = st.selectbox('Matéria-prima', [m['SK'] for m in options], format_func=lambda i: next(m['name']+' · '+m['unit'] for m in options if m['SK'] == i))
    m = next(m for m in options if m['SK'] == identifier)
    if section == 'Editar matéria-prima':
        with st.form(f"edit_material_{identifier}_{m['revision']}"):
            data = deepcopy(m)
            data['name'] = st.text_input('Nome', m['name'])
            data['brand'] = st.text_input('Marca', m['brand'])
            data['pack'] = suggested_input('Unidade de compra', PURCHASE_UNITS, [item['pack'] for item in items], m['pack'])
            data['price'] = n('Preço da embalagem (R$)', m['price'])
            data['cost_mode'], data['unit_price'] = cost_fields(m, key=identifier)
            data['minimum'] = n('Estoque mínimo', m['minimum'])
            data['active'] = st.checkbox('Ativo', m['active'])
            st.caption(f"{float(m['per']):g} {m['unit']} por embalagem. Quantidade e unidade de uso são preservadas para proteger o histórico.")
            if st.form_submit_button('Salvar alterações'):
                action(lambda: repo.save_material(data), 'Matéria-prima atualizada.')
        return
    token_key = 'stock_token_'+identifier+'_'+section
    token = st.session_state.setdefault(token_key, str(uuid4()))
    with st.form('movement_'+token):
        kind = 'Entrada de compra' if section == 'Registrar entrada' else st.selectbox('Tipo', ['Perda', 'Ajuste de saída', 'Ajuste de entrada'])
        quantity = st.number_input('Embalagens compradas' if section == 'Registrar entrada' else 'Quantidade na unidade de uso', min_value=.000001, value=1.)
        price = n('Preço pago por embalagem (R$)', m['price']) if section == 'Registrar entrada' else 0
        note = st.text_input('Fornecedor / observação' if section == 'Registrar entrada' else 'Motivo obrigatório')
        st.caption(f"Saldo: {float(m['stock']):g} {m['unit']}. Cada embalagem contém {float(m['per']):g} {m['unit']}.")
        if m.get('cost_mode') == 'unit':
            st.caption(f"O custo por uso continua {money(repo.unit_cost(m))}, informado no cadastro; o preço pago fica só no histórico.")
        if st.form_submit_button('Confirmar movimentação'):
            def commit():
                repo.move(identifier, kind, quantity, token, price, note)
                st.session_state[token_key] = str(uuid4())
            action(commit, 'Movimentação registrada e saldo atualizado.')


def production_page():
    st.caption('PRODUÇÃO')
    st.title('Registrar produção')
    st.caption('Informe o que foi produzido para dar baixa nas matérias-primas da ficha técnica. Não há estoque de produtos prontos.')
    notice()
    products = table('produtos')
    if products.empty:
        st.info('Cadastre um produto com ficha técnica antes de registrar produções.')
        return
    items = repo.materials()
    recipes = repo.product_costs_many(products['id_produto'].astype(str).tolist())
    names = {str(r['id_produto']): f"{r['nome_produto']} ({r['id_produto']})" for _, r in products.iterrows()}
    ready = [pid for pid in names if recipes[pid]['recipe']]
    register, history = st.tabs(['Nova produção', 'Histórico'])
    with register:
        if not ready:
            st.info('Nenhum produto tem matérias-primas na ficha técnica. Inclua-as em Produtos › Editar.')
        else:
            pid = st.selectbox('Produto', ready, format_func=names.get, key='production_product')
            quantity = st.number_input('Quantidade produzida', min_value=1, value=1, step=1, key='production_quantity')
            plan = repo.production_plan(pid, quantity, items, recipes[pid])
            st.dataframe(pd.DataFrame([{
                'Matéria-prima': r['name'], 'Por unidade': f"{float(r['per_unit']):g} {r['unit']}",
                'Necessário': f"{float(r['needed']):g} {r['unit']}", 'Saldo atual': f"{float(r['stock']):g}",
                'Saldo após': f"{float(r['after']):g}", 'Situação': 'OK' if r['ok'] else 'Falta material',
            } for r in plan]), hide_index=True, width='stretch')
            limit = repo.max_producible(plan)
            st.caption(f'Com o estoque atual dá para produzir até {limit} unidade(s) deste produto.')
            short = not all(r['ok'] for r in plan)
            if short:
                st.warning('Estoque insuficiente. Registre uma entrada em Matérias-primas ou reduza a quantidade.')
            token_key = 'production_token_'+pid
            token = st.session_state.setdefault(token_key, str(uuid4()))
            confirm = st.checkbox('Confirmo a produção e a baixa dos materiais', key='production_confirm_'+token)
            if st.button('Registrar produção', type='primary', disabled=short or not confirm, key='production_submit'):
                def commit():
                    repo.produce(pid, quantity, token, names[pid])
                    st.session_state[token_key] = str(uuid4())
                action(commit, f'Produção de {quantity} unidade(s) registrada. Estoque atualizado.')
    with history:
        events = repo.productions()
        if not events:
            st.info('Nenhuma produção registrada.')
        else:
            st.dataframe(pd.DataFrame([{
                'Data (UTC)': e['date'][:16].replace('T', ' '),
                'Produto': e.get('product_name') or names.get(str(e['product_id']), e['product_id']),
                'Quantidade': int(e['quantity']), 'Custo unitário': money(e.get('unit_cost', 0)),
                'Custo total': money(e.get('unit_cost', 0)*e['quantity']),
                'Materiais': ', '.join(f"{float(c['quantity']):g} {c['unit']} {c['material_name']}" for c in e.get('consumed', [])),
            } for e in events]), hide_index=True, width='stretch')


def jump(page, nav, product_action=None):
    st.session_state._active_page = page
    st.session_state.page = page
    st.session_state.main_navigation = nav
    if product_action:
        st.session_state.product_action = product_action


def home_page():
    st.caption('SEU ATELIÊ, ORGANIZADO')
    st.title('Tudo pronto para criar')
    st.caption('Acompanhe seus produtos, materiais e próximas produções.')
    products = table('produtos')
    try:
        items = repo.materials()
    except store.StorageError as exc:
        st.info('O catálogo existente continua disponível. '+str(exc))
        items = []
    low = [m for m in items if m['active'] and m['stock'] <= m['minimum']]
    stats = st.columns(4)
    stats[0].metric('Produtos cadastrados', len(products))
    stats[1].metric('Matérias-primas ativas', sum(bool(m['active']) for m in items))
    stats[2].metric('Precisam de reposição', len(low))
    stats[3].metric('Valor em estoque', money(sum(m['stock']*repo.unit_cost(m) for m in items)))
    st.caption('Valor de estoque estimado pelo último preço de compra.')
    left, right = st.columns([1.2, 1], gap='large')
    with left, st.container(border=True, key="card_home_actions"):
        st.subheader('O que vamos fazer hoje?')
        st.button('＋ Cadastrar produto', type='primary', use_container_width=True, on_click=jump, args=('📝 Cadastrar produto', 'Produtos', 'Cadastrar'))
        st.button('↗ Matérias-primas e entradas', use_container_width=True, on_click=jump, args=('📦 Matérias-primas e estoque', 'Matérias-primas'))
        st.button('✦ Registrar produção', use_container_width=True, on_click=jump, args=('🏭 Produção', 'Produção'))
        st.info('Cadastre o produto com a ficha técnica e registre a produção para dar baixa nas matérias-primas.')
    with right, st.container(border=True, key="card_home_stock"):
        st.subheader('Atenção ao estoque')
        if not low:
            st.success('Todos os materiais estão acima do mínimo.' if items else 'Cadastre materiais para acompanhar a reposição.')
        for m in low:
            st.write('**'+m['name']+'**')
            st.caption(f"Saldo: {float(m['stock']):g} {m['unit']} · mínimo {float(m['minimum']):g}")
        st.button('Ver todos os materiais →', on_click=jump, args=('📦 Matérias-primas e estoque', 'Matérias-primas'))
