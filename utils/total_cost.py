"""Estimate full product costs using the most expensive configured platform.

The catalog's 'custo' column remains the manually entered base cost. Never
overwrite it with a derived total, otherwise editing would double count costs.
"""
from decimal import Decimal

from utils.pricing import decimal


def estimate(base_cost, selling_price, production_cost=0, platforms=None):
    base = decimal(base_cost, "Custo informado")
    price = decimal(selling_price, "Preço de venda")
    production = decimal(production_cost, "Custo de produção")
    candidates = []
    for platform in platforms or []:
        commission = decimal(platform["commission"], "Comissão")
        fixed = decimal(platform["fixed"], "Tarifa fixa")
        freight = decimal(platform["freight"], "Frete")
        if commission >= 100:
            raise ValueError("A comissão da plataforma deve ser inferior a 100%.")
        fee = price * commission / Decimal("100")
        candidates.append((fee + fixed + freight, platform["name"], fee, fixed, freight))
    extra, name, commission, fixed, freight = max(candidates, key=lambda row: row[0]) if candidates else (
        Decimal("0"), "Nenhuma plataforma cadastrada", Decimal("0"), Decimal("0"), Decimal("0")
    )
    total = base + production + extra
    return {
        "base": base, "production": production, "platform": name,
        "commission": commission, "fixed": fixed, "freight": freight,
        "total": total, "profit": price - total,
        "margin": (price - total) / price * 100 if price else Decimal("0"),
    }


def estimate_for_product(product_id, base_cost, selling_price):
    """Production data is optional for new products and unconfigured AWS."""
    import streamlit as st
    if not product_id or "aws" not in st.secrets:
        return estimate(base_cost, selling_price)
    from repositories import production
    data = production.product_costs(product_id)
    config = production.settings()
    items = production.materials()
    production_total = production.breakdown(data, config, items)["total"]
    return estimate(base_cost, selling_price, production_total, data.get("platforms", []))
