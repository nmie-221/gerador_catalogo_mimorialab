"""Catalog persistence in DynamoDB. No Google Sheets calls after cutover."""
import pandas as pd
import streamlit as st
from services import dynamodb as db
from services.google_sheets import SHEETS, HEADERS

INDEX = "MIMORIALAB#CATALOG#PRODUCTS"
DOMAINS = {k: "MIMORIALAB#CATALOG#" + k.upper() for k in SHEETS if k != "produtos"}


def backend_setting():
    """Value of [catalog] backend, tolerating common placements in the Secrets."""
    for section in ("catalog", "aws"):
        value = st.secrets.get(section, {})
        if hasattr(value, "get") and value.get("backend"):
            return str(value.get("backend")).strip().lower()
    return str(st.secrets.get("backend", "sheets")).strip().lower()


def enabled():
    return backend_setting() == "dynamodb"


def identifier(kind, row):
    return str(row["id_produto" if kind == "produtos" else "id"])


def key(kind, rid):
    return ("MIMORIALAB#PRODUCT#" + str(rid), "DETAILS") if kind == "produtos" else (DOMAINS[kind], str(rid))


def record(kind, row):
    rid = identifier(kind, row)
    pk, sk = key(kind, rid)
    values = {column: row.get(column, "") for column in HEADERS[SHEETS[kind]]}
    return {"PK": pk, "SK": sk, "revision": 1, **values}


def read(kind):
    if kind == "produtos":
        keys = [key(kind, item["SK"]) for item in db.query(INDEX)]
        details = db.batch_get(keys)
        records = []
        for pk, sk in keys:
            if (pk, sk) not in details:
                raise db.StorageError("Índice de produtos inconsistente: " + pk.rsplit("#", 1)[-1])
            records.append(details[(pk, sk)])
    else:
        records = db.query(DOMAINS[kind])
    cols = HEADERS[SHEETS[kind]]
    return pd.DataFrame([{col: r.get(col, "") for col in cols} for r in records], columns=cols)


def insert(kind, row, extra=()):
    """Insert a record; `extra` (item, expected_revision) pairs are written atomically with it."""
    item = record(kind, row)
    if kind == "produtos":
        rid = identifier(kind, row)
        index = {"PK": INDEX, "SK": rid, "revision": 1}
        db.transaction([(item, None), (index, None), *extra])
    elif extra:
        db.transaction([(item, None), *extra])
    else:
        db.put(item)


def update(kind, row, extra=()):
    pk, sk = key(kind, identifier(kind, row))
    previous = db.get(pk, sk)
    if not previous:
        raise ValueError("Registro não encontrado no DynamoDB.")
    item = record(kind, row)
    item["revision"] = int(previous["revision"]) + 1
    if extra:
        db.transaction([(item, previous["revision"]), *extra])
    else:
        db.put(item, previous["revision"])


def remove(kind, rid, extra_keys=()):
    pk, sk = key(kind, rid)
    if kind == "produtos":
        db.delete_many([(pk, sk), (INDEX, str(rid)), *extra_keys])
    else:
        db.delete(pk, sk)
