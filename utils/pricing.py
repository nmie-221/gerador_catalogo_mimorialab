from decimal import Decimal, InvalidOperation, ROUND_CEILING


def decimal(value, label='Valor', positive=False):
    text = str(value).strip()
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f'{label}: informe um número válido.') from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f'{label}: informe um valor {"maior que zero" if positive else "não negativo"}.')
    return result


def quote(cost, commission, fixed, freight, margin):
    cost, commission, fixed, freight, margin = [decimal(v) for v in [cost, commission, fixed, freight, margin]]
    denominator = 1-(commission+margin)/100
    if denominator <= 0:
        raise ValueError('Comissão + margem devem somar menos de 100%.')
    price = ((cost+fixed+freight)/denominator).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    fee = price*commission/100
    profit = price-cost-fixed-freight-fee
    return dict(price=price, commission=fee, fixed=fixed, freight=freight, profit=profit, margin=profit/price*100 if price else Decimal(0))
