"""DynamoDB-backed catalog. Legacy Sheets remains available during migration."""
from decimal import Decimal

import pandas as pd
import streamlit as st

from services import dynamodb as store
from services.google_sheets import HEADERS

PARTITIONS = {
    "produtos": "MIMORIALAB#CATALOG#PRODUCTS",
    "categorias": "MIMORIALAB#CATALOG#CATEGORIES",
    "tamanhos": "MIMORIALAB#CATALOG#SIZES",
    "cores": "MIMORIALAB#CATALOG#COLORS",
    "materiais": "MIMORIALAB#CATALOG#MATERIALS",
    "kits": "MIMORIALAB#CATALOG#KITS",
}
SHEET_NAMES = {
    "produtos": "PRODUTOS", "categorias": "CATEGORIAS",
    "tamanhos": "TAMANHOS", "cores": "CORES",
    "materiais": "MATERIAIS", "kits": "KIT",
}


def enabled():
    return str(st.secrets.get("catalog", {}).get("backend", "sheets")).strip().lower() == "dynamodb"


def key(kind, identifier):
    if kind == "produtos":
        # Preserve the existing PK used by the production COSTS record.
        return "MIMORIALAB#PRODUCT#" + str(identifier), "DETAILS"
    return PARTITIONS[kind], str(identifier)


def read(kind):
    if kind == "produtos":
        # A separate index of product IDs avoids table scans.
        indexes = store.query(PARTITIONS[kind])
        records = [store.get(*key(kind, entry["SK"])) for entry in indexes]
        records = [record for record in records if record is not None]
    else:
        records = store.query(PARTITIONS[kind])
    columns = HEADERS[SHEET_NAMES[kind]]
    return pd.DataFrame([{col: record.get(col, "") for col in columns} for record in records], columns=columns)


def save(kind, row, create=False):
    columns = HEADERS[SHEET_NAMES[kind]]
    data = dict(zip(columns, row))
    identifier = str(data["id_produto" if kind == "produtos" else "id"])
    pk, sk = key(kind, identifier)
    previous = store.get(pk, sk)
    if create and previous:
        raise ValueError("Registro já existente no DynamoDB.")
    if not create and not previous:
        raise ValueError("Registro não encontrado no DynamoDB.")
    revision = int(previous.get("revision", 0)) if previous else 0
    item = {"PK": pk, "SK": sk, "revision": revision + 1, **data}
    if kind == "produtos" and create:
        # Write product + catalog index atomically to keep listings consistent.
        index = {"PK": PARTITIONS[kind], "SK": identifier, "revision": 1}
        store.transaction([(item, None), (index, None)], "catalog-create-" + identifier)
    else:
        store.put(item, revision if previous else None)


def remove(kind, identifier):
    # DynamoDB delete requires conditional delete; implemented by the storage service.
    pk, sk = key(kind, identifier)
    store.delete(pk, sk)
    if kind == "produtos":
        store.delete(PARTITIONS[kind], str(identifier))
