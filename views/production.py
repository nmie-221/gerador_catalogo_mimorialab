"""Native Streamlit screens backed by the production repository."""
from copy import deepcopy
from uuid import uuid4

import pandas as pd
import streamlit as st

from repositories import production as repo
from repositories.data import table
from services import dynamodb as store
from services.google_sheets import update_row
from utils.pricing import quote


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
    section = st.selectbox('Configuração', ['Hora de mão de obra', 'Custo por impressão'], key='costs_section')
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
                per=suggested_input('Quantidade de uso por embalagem', ['1', '10', '20', '50', '100', '250', '500', '1000'], current='500'),
                unit=suggested_input('Unidade de uso', USAGE_UNITS, [m['unit'] for m in items], 'folha'),
                price=n('Preço de uma embalagem (R$)'), minimum=n('Estoque mínimo na unidade de uso'), stock=0, active=True,
            )
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
        total = sum(float(m['stock'])*float(m['price'])/float(m['per']) for m in items)
        st.metric('Valor estimado em estoque', money(total))
        st.caption('Estimativa pelo último preço de compra. Não é custo médio contábil.')
        for m in items:
            if search.casefold() not in (m['name']+' '+m['brand']).casefold():
                continue
            with st.container(border=True, key="card_material_"+m["SK"]):
                st.subheader(m['name'])
                st.caption(m['brand']+' · '+('Ativo' if m['active'] else 'Inativo'))
                st.write(f"Saldo: **{float(m['stock']):g} {m['unit']}** · Custo por uso: **{money(m['price']/m['per'])}**")
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
        if st.form_submit_button('Confirmar movimentação'):
            def commit():
                repo.move(identifier, kind, quantity, token, price, note)
                st.session_state[token_key] = str(uuid4())
            action(commit, 'Movimentação registrada e saldo atualizado.')


def recipe_page():
    st.caption('DA IDEIA AO PRODUTO')
    st.title('Ficha técnica e preço')
    st.caption('Defina o consumo para uma unidade e compare os preços por plataforma.')
    notice()
    products = table('produtos')
    if products.empty:
        st.info('Cadastre um produto antes de configurar a ficha.')
        return
    pid = st.selectbox('Produto', products['id_produto'].astype(str).tolist(), format_func=lambda i: str(products.loc[products['id_produto'].astype(str) == i, 'nome_produto'].iloc[0]), key='cost_product')
    data = repo.product_costs(pid)
    items = repo.materials()
    known = {m['SK']: m for m in items}
    config = repo.settings()
    left, right = st.columns([1.2, 1], gap='large')
    with left:
        st.subheader('Materiais por unidade do produto')
        for index, row in enumerate(data['recipe']):
            m = known.get(row['material_id'])
            with st.expander(m['name'] if m else 'Material não encontrado'):
                with st.form(f'recipe_{pid}_{row["material_id"]}_{data["revision"]}'):
                    quantity = st.number_input('Consumo por produto'+(' em '+m['unit'] if m else ''), min_value=.000001, value=float(row['quantity']))
                    remove = st.checkbox('Remover este material da ficha')
                    if st.form_submit_button('Salvar item da ficha'):
                        updated = deepcopy(data)
                        if remove:
                            updated['recipe'].pop(index)
                        else:
                            updated['recipe'][index]['quantity'] = quantity
                        action(lambda: repo.save_product_costs(updated), 'Ficha atualizada.')
        available = [m for m in items if m['active'] and not any(r['material_id'] == m['SK'] for r in data['recipe'])]
        with st.expander('Adicionar matéria-prima'):
            if available:
                with st.form(f"add_recipe_{pid}_{data['revision']}"):
                    mid = st.selectbox('Material', [m['SK'] for m in available], format_func=lambda i: known[i]['name']+' · '+known[i]['unit'])
                    quantity = st.number_input('Consumo para uma unidade', min_value=.000001, value=1.)
                    if st.form_submit_button('Adicionar à ficha'):
                        updated = deepcopy(data)
                        updated['recipe'].append(dict(material_id=mid, quantity=quantity))
                        action(lambda: repo.save_product_costs(updated), 'Material adicionado à ficha.')
            else:
                st.info('Cadastre uma matéria-prima ativa para adicioná-la aqui.')
    with right:
        st.subheader('Tempo e impressão')
        with st.form(f"production_params_{pid}_{data['revision']}"):
            updated = deepcopy(data)
            updated['minutes'] = n('Tempo por produto (minutos)', data['minutes'])
            profiles = ['']+[p['id'] for p in config['prints']]
            updated['print_id'] = st.selectbox('Perfil de impressão', profiles, index=profiles.index(data['print_id']) if data['print_id'] in profiles else 0, format_func=lambda i: 'Sem impressão' if not i else next(p['name'] for p in config['prints'] if p['id'] == i))
            updated['prints'] = st.number_input('Lados impressos por produto', min_value=0, value=int(data['prints']))
            updated['other'] = n('Outros custos por produto (R$)', data['other'])
            updated['margin'] = st.number_input('Margem sobre o preço de venda (%)', min_value=0., max_value=99., value=float(data['margin']))
            if st.form_submit_button('Salvar parâmetros do produto'):
                action(lambda: repo.save_product_costs(updated), 'Parâmetros salvos neste produto.')
        st.subheader('Taxas deste produto')
        for index, platform in enumerate(data['platforms']):
            with st.expander(platform['name']):
                with st.form(f"platform_{pid}_{platform['id']}_{data['revision']}"):
                    edited = platform_fields(platform)
                    remove = st.checkbox('Remover esta plataforma do produto')
                    if st.form_submit_button('Salvar taxas deste produto'):
                        updated = deepcopy(data)
                        if remove:
                            updated['platforms'].pop(index)
                        else:
                            updated['platforms'][index] = dict(id=platform['id'], **edited)
                        action(lambda: repo.save_product_costs(updated), 'Taxas atualizadas apenas neste produto.')
        with st.expander('Adicionar plataforma ao produto'):
            with st.form(f"new_platform_{pid}_{data['revision']}"):
                platform = platform_fields(dict(name='', commission=0, fixed=0, freight=0))
                if st.form_submit_button('Adicionar plataforma'):
                    updated = deepcopy(data)
                    updated['platforms'].append(dict(id=uuid4().hex, **platform))
                    action(lambda: repo.save_product_costs(updated), 'Plataforma adicionada a este produto.')
        st.caption('Tarifa e frete são reservados integralmente por produto. Não abatemos frete recebido. Impostos e encargos não informados não estão incluídos.')
    costs = repo.breakdown(data, config, items)
    st.metric('Custo completo por produto', money(costs['total']))
    st.write({k: money(v) for k, v in {'Materiais': costs['materials'], 'Mão de obra': costs['labor'], 'Impressão': costs['printing'], 'Outros': costs['other']}.items()})
    results = []
    invalid = False
    for platform in data['platforms']:
        try:
            result = quote(costs['total'], platform['commission'], platform['fixed'], platform['freight'], data['margin'])
        except ValueError as exc:
            invalid = True
            st.error(platform['name']+': '+str(exc))
        else:
            results.append((platform, result))
    if results:
        st.dataframe(pd.DataFrame([{'Plataforma': p['name'], 'Preço sugerido': money(r['price']), 'Comissão': money(r['commission']), 'Tarifa fixa': money(r['fixed']), 'Frete': money(r['freight']), 'Lucro': money(r['profit']), 'Margem efetiva': f"{float(r['margin']):.2f}%"} for p, r in results]), hide_index=True, use_container_width=True)
        selected = st.selectbox('Aplicar preço de', ['highest']+[p['id'] for p, _ in results], format_func=lambda i: 'Maior preço sugerido' if i == 'highest' else next(p['name'] for p, _ in results if p['id'] == i))
        price = max(r['price'] for _, r in results) if selected == 'highest' else next(r['price'] for p, r in results if p['id'] == selected)
        confirm = st.checkbox('Confirmo atualizar o preço e o custo do produto no catálogo')
        if st.button('Aplicar preço ao produto', disabled=not confirm or (selected == 'highest' and invalid)):
            # Refresh physical row position before writing the existing catalog.
            from services.google_sheets import read_sheet
            read_sheet.clear()
            fresh = table('produtos')
            positions = [i for i, value in enumerate(fresh['id_produto']) if str(value) == pid]
            if len(positions) != 1:
                st.error('Produto não encontrado ou ID duplicado. Atualize a página.')
            else:
                position = positions[0]
                row = fresh.iloc[position].tolist()
                row[6], row[7] = float(price), float(costs['total'])
                action(lambda: update_row('PRODUTOS', position+2, row), 'Preço e custo aplicados ao catálogo.')
    else:
        st.info('Cadastre as plataformas deste produto para comparar preços.')
    with st.expander('Registrar produção e baixar estoque'):
        token_key = 'production_token_'+pid
        token = st.session_state.setdefault(token_key, str(uuid4()))
        with st.form('produce_'+token):
            quantity = st.number_input('Quantidade de produtos produzidos', min_value=1, value=1)
            for row in data['recipe']:
                m = known.get(row['material_id'])
                if m:
                    st.caption(f"Por produto: {float(row['quantity']):g} {m['unit']} de {m['name']}. Saldo: {float(m['stock']):g}.")
            confirm = st.checkbox('Confirmo a produção e a baixa dos materiais')
            if st.form_submit_button('Confirmar produção'):
                if not confirm:
                    st.error('Confirme a produção para continuar.')
                else:
                    def commit():
                        repo.produce(pid, quantity, token)
                        st.session_state[token_key] = str(uuid4())
                    action(commit, 'Produção registrada. Estoque atualizado.')


def platform_fields(p):
    return dict(name=st.text_input('Nome da plataforma', p['name']), commission=st.number_input('Comissão máxima (%)', min_value=0., max_value=99., value=float(p['commission'])), fixed=n('Tarifa fixa por produto (R$)', p['fixed']), freight=n('Frete reservado por produto (R$)', p['freight']))


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
    stats[3].metric('Valor em estoque', money(sum(m['stock']*m['price']/m['per'] for m in items)))
    st.caption('Valor de estoque estimado pelo último preço de compra.')
    left, right = st.columns([1.2, 1], gap='large')
    with left, st.container(border=True, key="card_home_actions"):
        st.subheader('O que vamos fazer hoje?')
        st.button('＋ Cadastrar produto', type='primary', use_container_width=True, on_click=jump, args=('📝 Cadastrar produto', 'Produtos', 'Cadastrar'))
        st.button('↗ Matérias-primas e entradas', use_container_width=True, on_click=jump, args=('📦 Matérias-primas e estoque', 'Matérias-primas'))
        st.button('✦ Ficha técnica e produção', use_container_width=True, on_click=jump, args=('🧾 Ficha e preço', 'Ficha e preço'))
        st.info('Cadastre o material, monte a ficha técnica e confirme a produção para dar baixa no estoque.')
    with right, st.container(border=True, key="card_home_stock"):
        st.subheader('Atenção ao estoque')
        if not low:
            st.success('Todos os materiais estão acima do mínimo.' if items else 'Cadastre materiais para acompanhar a reposição.')
        for m in low:
            st.write('**'+m['name']+'**')
            st.caption(f"Saldo: {float(m['stock']):g} {m['unit']} · mínimo {float(m['minimum']):g}")
        st.button('Ver todos os materiais →', on_click=jump, args=('📦 Matérias-primas e estoque', 'Matérias-primas'))
