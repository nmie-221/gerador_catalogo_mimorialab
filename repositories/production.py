"""Production data (materials, recipes, costs and stock events) in DynamoDB."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from services import dynamodb as store
from utils.pricing import decimal, quote

MATERIALS = 'MIMORIALAB#MATERIALS'
EVENTS = 'MIMORIALAB#STOCK_EVENTS'
COSTS = 'MIMORIALAB#COSTS'


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def settings():
    return store.get(COSTS, 'SETTINGS') or dict(PK=COSTS, SK='SETTINGS', revision=0, hour_mode='direct', monthly=0, hours=100, hourly=0, prints=[], marketplace_defaults=[])


def save_settings(data):
    value = deepcopy(data)
    if value['hour_mode'] not in ['direct', 'monthly']:
        raise ValueError('Forma de cálculo da hora inválida.')
    value['monthly'] = decimal(value['monthly'])
    value['hours'] = decimal(value['hours'], 'Horas produtivas', positive=True)
    value['hourly'] = decimal(value['hourly'])
    for p in value['prints']:
        if not p['name'].strip():
            raise ValueError('Informe o nome do perfil.')
        for key in ['ink', 'maintenance', 'energy']:
            p[key] = decimal(p[key])
        p['yield'] = decimal(p['yield'], 'Rendimento', positive=True)
        if p['yield'] != p['yield'].to_integral_value():
            raise ValueError('O rendimento deve ser inteiro.')
    if len({p['name'].strip().casefold() for p in value['prints']}) != len(value['prints']):
        raise ValueError('Os perfis de impressão devem ter nomes diferentes.')
    defaults = value.get('marketplace_defaults', [])
    names = set()
    for platform in defaults:
        name = str(platform.get('name', '')).strip()
        if not name or name.casefold() in names:
            raise ValueError('Cada plataforma deve ter um nome único.')
        names.add(name.casefold())
        for field in ('commission', 'fixed', 'freight'):
            platform[field] = decimal(platform.get(field, 0))
        if platform['commission'] >= 100:
            raise ValueError('Comissão deve ser menor que 100%.')
    value['marketplace_defaults'] = defaults
    expected = value['revision'] or None
    value['revision'] += 1
    store.put(value, expected)


def hourly(config):
    return decimal(config['hourly']) if config['hour_mode'] == 'direct' else decimal(config['monthly'])/decimal(config['hours'], positive=True)


def print_rate(p):
    return decimal(p['ink'])/decimal(p['yield'], positive=True)+decimal(p['maintenance'])+decimal(p['energy'])


def materials():
    return store.query(MATERIALS)


COST_MODES = {'pack': 'Calcular pelo preço da embalagem', 'unit': 'Informar o preço por unidade de uso'}


def unit_cost(m):
    """Cost of one unit of use: typed directly, or pack price / units per pack."""
    if m.get('cost_mode') == 'unit':
        return decimal(m.get('unit_price') or 0)
    return decimal(m['price'])/decimal(m['per'], positive=True)


def save_material(data):
    value = deepcopy(data)
    if not all(isinstance(value.get(k), str) and value[k].strip() for k in ['name', 'brand', 'pack', 'unit']):
        raise ValueError('Preencha nome, marca e unidades de compra e uso.')
    value['per'] = decimal(value['per'], 'Quantidade por embalagem', positive=True)
    for key in ['price', 'minimum', 'stock']:
        value[key] = decimal(value.get(key, 0), key)
    value['cost_mode'] = value.get('cost_mode') or 'pack'
    if value['cost_mode'] not in COST_MODES:
        raise ValueError('Forma de custo inválida.')
    value['unit_price'] = decimal(value.get('unit_price') or 0, 'Preço por unidade de uso')
    if value['cost_mode'] == 'unit' and not value['unit_price']:
        raise ValueError('Informe o preço por unidade de uso.')
    if 'PK' not in value:
        value.update(PK=MATERIALS, SK=uuid4().hex, revision=0, stock=Decimal(0))
    else:
        previous = store.get(MATERIALS, value['SK'])
        if not previous or previous['revision'] != value['revision']:
            raise store.ConflictError('Material alterado em outra sessão. Atualize a página.')
        if any(value[k] != previous[k] for k in ['unit', 'per', 'stock']):
            raise ValueError('Unidade, quantidade por embalagem e saldo não podem ser alterados no cadastro. Use movimentações para mudar o estoque.')
    expected = value['revision'] or None
    value['revision'] += 1
    store.put(value, expected)
    return value


def costs_key(pid):
    return 'MIMORIALAB#PRODUCT#'+str(pid), 'COSTS'


def empty_costs(pid):
    pk, sk = costs_key(pid)
    return dict(PK=pk, SK=sk, revision=0, recipe=[], platforms=[], minutes=0, print_id='', prints=0, other=0, extras=[], margin=30)


def _with_defaults(pid, data):
    result = empty_costs(pid)
    result.update(data or {})
    return result


def product_costs(pid):
    return _with_defaults(pid, store.get(*costs_key(pid)))


def product_costs_many(pids):
    """Recipes for many products in batched reads (missing ones come back empty)."""
    found = store.batch_get([costs_key(pid) for pid in pids])
    return {str(pid): _with_defaults(pid, found.get(costs_key(pid))) for pid in pids}


def has_costs(data):
    return bool(data['recipe'] or data['minutes'] or data['prints'] or data['other'] or data.get('extras'))


def prepare_product_costs(data):
    """Validate a recipe and return (item, expected_revision) for a conditional write."""
    value = deepcopy(data)
    value.setdefault('extras', [])
    known = {m['SK']: m for m in materials()}
    ids = []
    for row in value['recipe']:
        if row['material_id'] not in known:
            raise ValueError('Matéria-prima da ficha não encontrada.')
        row['quantity'] = decimal(row['quantity'], 'Consumo', positive=True)
        ids.append(row['material_id'])
    if len(ids) != len(set(ids)):
        raise ValueError('Uma matéria-prima não pode aparecer duas vezes na mesma ficha.')
    names = []
    for p in value['platforms']:
        if not p['name'].strip():
            raise ValueError('Informe o nome da plataforma.')
        names.append(p['name'].strip().casefold())
        for key in ['commission', 'fixed', 'freight']:
            p[key] = decimal(p[key])
        if p['commission'] >= 100:
            raise ValueError('Comissão deve ser menor que 100%.')
    if len(names) != len(set(names)):
        raise ValueError('Plataforma já cadastrada neste produto.')
    for key in ['minutes', 'prints', 'other', 'margin']:
        value[key] = decimal(value[key])
    if value['prints'] != value['prints'].to_integral_value():
        raise ValueError('Quantidade de lados impressos deve ser inteira.')
    if value['prints'] and not any(p['id'] == value['print_id'] for p in settings()['prints']):
        raise ValueError('Selecione um perfil de impressão válido.')
    if value['margin'] >= 100:
        raise ValueError('Margem deve ser menor que 100%.')
    extras = []
    for row in value.get('extras', []):
        name = ' '.join(str(row.get('name', '')).split())
        amount = decimal(row.get('value', 0), 'Valor do custo')
        if not name and not amount:
            continue  # blank line left in the form
        if not name:
            raise ValueError('Informe a descrição de cada custo adicional.')
        extras.append(dict(name=name, value=amount))
    value['extras'] = extras
    expected = value['revision'] or None
    value['revision'] += 1
    return value, expected


def save_product_costs(data):
    value, expected = prepare_product_costs(data)
    store.put(value, expected)
    return value


def breakdown(data, config, items):
    known = {m['SK']: m for m in items}
    material_cost = Decimal(0)
    for row in data['recipe']:
        m = known.get(row['material_id'])
        if not m:
            raise ValueError('Matéria-prima da ficha não encontrada.')
        material_cost += unit_cost(m)*decimal(row['quantity'])
    labor = hourly(config)*decimal(data['minutes'])/60
    p = next((p for p in config['prints'] if p['id'] == data['print_id']), None)
    if data['prints'] and p is None:
        raise ValueError('Perfil de impressão não encontrado.')
    printing = print_rate(p)*decimal(data['prints']) if p else Decimal(0)
    other = decimal(data['other'])+sum((decimal(row['value']) for row in data.get('extras', [])), Decimal(0))
    return dict(materials=material_cost, labor=labor, printing=printing, other=other, total=material_cost+labor+printing+other)


def move(material_id, kind, quantity, token, price=0, note=''):
    if store.get(EVENTS, token):
        return  # repeated successful submission
    m = store.get(MATERIALS, material_id)
    if not m or not m['active']:
        raise ValueError('Escolha uma matéria-prima ativa.')
    qty = decimal(quantity, 'Quantidade', positive=True)
    if kind == 'Entrada de compra':
        qty *= decimal(m['per'], positive=True)
        m['price'] = decimal(price, 'Preço da embalagem')
    elif kind in ['Perda', 'Ajuste de saída']:
        qty = -qty
    elif kind != 'Ajuste de entrada':
        raise ValueError('Tipo de movimentação inválido.')
    if kind != 'Entrada de compra' and not note.strip():
        raise ValueError('Informe o motivo do ajuste ou perda.')
    if decimal(m['stock'])+qty < 0:
        raise ValueError('Estoque insuficiente. Nenhuma alteração foi feita.')
    revision = m['revision']
    m.update(stock=decimal(m['stock'])+qty, revision=revision+1)
    event = dict(PK=EVENTS, SK=token, date=timestamp(), type=kind, material_id=material_id, material_name=m['name'], quantity=qty, unit=m['unit'], price=m['price'], note=note)
    store.transaction([(m, revision), (event, None)], token)


def production_plan(pid, quantity, items=None, data=None):
    """Materials needed to produce `quantity` units, with the resulting balance."""
    data = data or product_costs(pid)
    known = {m['SK']: m for m in (items if items is not None else materials())}
    count = decimal(quantity, 'Quantidade produzida')
    rows = []
    for row in data['recipe']:
        m = known.get(row['material_id'])
        per_unit = decimal(row['quantity'])
        stock = decimal(m['stock']) if m else Decimal(0)
        needed = per_unit*count
        rows.append(dict(material_id=row['material_id'], name=m['name'] if m else 'Material não encontrado',
                         unit=m['unit'] if m else '', per_unit=per_unit, needed=needed, stock=stock,
                         after=stock-needed, ok=bool(m and m['active'] and stock >= needed),
                         max_units=int(stock//per_unit) if m and m['active'] and per_unit else 0))
    return rows


def max_producible(rows):
    return min((r['max_units'] for r in rows), default=0)


def productions():
    return sorted((e for e in store.query(EVENTS) if e.get('type') == 'Produção'), key=lambda e: e['date'], reverse=True)


def produce(pid, quantity, token, product_name=''):
    if store.get(EVENTS, token):
        return
    count = decimal(quantity, 'Quantidade produzida', positive=True)
    if count != count.to_integral_value():
        raise ValueError('Informe uma quantidade inteira de produtos.')
    data = product_costs(pid)
    if not data['recipe']:
        raise ValueError('Cadastre a ficha técnica antes de registrar a produção.')
    if len(data['recipe']) > 98:
        raise ValueError('Limite de 98 matérias-primas por produção.')
    items = materials()
    known = {m['SK']: m for m in items}
    needed = {}
    for row in data['recipe']:
        mid = row['material_id']
        needed[mid] = needed.get(mid, Decimal(0))+decimal(row['quantity'], positive=True)*count
    requests, consumed = [], []
    for mid, qty in needed.items():
        m = known.get(mid)
        if not m or not m['active'] or decimal(m['stock']) < qty:
            raise ValueError('Material inativo ou estoque insuficiente. Nenhuma baixa foi feita.')
        revision = m['revision']
        m.update(stock=decimal(m['stock'])-qty, revision=revision+1)
        requests.append((m, revision))
        consumed.append(dict(material_id=mid, material_name=m['name'], quantity=qty, unit=m['unit']))
    costs = breakdown(data, settings(), items)
    event = dict(PK=EVENTS, SK=token, type='Produção', product_id=str(pid), product_name=product_name, quantity=count, date=timestamp(), consumed=consumed, unit_cost=costs['total'])
    # Pin the recipe revision so a concurrent recipe edit cannot change this production.
    revision = data['revision']
    data['revision'] += 1
    data['has_production'] = True
    requests.extend([(data, revision), (event, None)])
    store.transaction(requests, token)
