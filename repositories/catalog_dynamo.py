"""Catalog persistence in DynamoDB. No Google Sheets calls after cutover."""
from decimal import Decimal
import pandas as pd
import streamlit as st
from services import dynamodb as db
from services.google_sheets import SHEETS, HEADERS

INDEX = "MIMORIALAB#CATALOG#PRODUCTS"
DOMAINS = {k: "MIMORIALAB#CATALOG#" + k.upper() for k in SHEETS if k != "produtos"}


def enabled():
    return str(st.secrets.get("catalog", {}).get("backend", "sheets")).lower() == "dynamodb"


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
        ids = db.query(INDEX)
        records = []
        for item in ids:
            detail = db.get(*key(kind, item["SK"]))
            if detail is None:
                raise db.StorageError("Índice de produtos inconsistente: " + str(item["SK"]))
            records.append(detail)
    else:
        records = db.query(DOMAINS[kind])
    cols = HEADERS[SHEETS[kind]]
    return pd.DataFrame([{col: r.get(col, "") for col in cols} for r in records], columns=cols)


def insert(kind, row):
    item = record(kind, row)
    if kind == "produtos":
        rid = identifier(kind, row)
        index = {"PK": INDEX, "SK": rid, "revision": 1}
        db.transaction([(item, None), (index, None)], None)
    else:
        db.put(item)


def update(kind, row):
    pk, sk = key(kind, identifier(kind, row))
    previous = db.get(pk, sk)
    if not previous:
        raise ValueError("Registro não encontrado no DynamoDB.")
    item = record(kind, row)
    item["revision"] = int(previous["revision"]) + 1
    db.put(item, previous["revision"])


def remove(kind, rid):
    pk, sk = key(kind, rid)
    if kind == "produtos":
        db.delete_many([(pk, sk), (INDEX, str(rid))])
    else:
        db.delete(pk, sk)


def import_sheet(kind, frame, dry_run=True):
    """Validate and import only missing records; never overwrite existing data."""
    if frame.empty:
        return {"source": 0, "existing": 0, "inserted": 0}
    rows = frame.to_dict("records")
    ids = [identifier(kind, row) for row in rows]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("IDs ausentes ou duplicados em " + kind)
    if kind == "produtos":
        skus = [str(r.get("sku", "")).strip() for r in rows]
        if not all(skus) or len(skus) != len(set(skus)):
            raise ValueError("SKUs ausentes ou duplicados.")
    existing = 0
    missing = []
    for row in rows:
        old = db.get(*key(kind, identifier(kind, row)))
        if old:
            existing += 1
            expected = record(kind, row)
            if any(str(old.get(k, "")) != str(v) for k, v in expected.items() if k not in ("PK", "SK", "revision")):
                raise ValueError("Conflito no registro " + identifier(kind, row) + ": DynamoDB diferente do Sheets.")
            if kind == "produtos" and not db.get(INDEX, identifier(kind, row)):
                raise ValueError("Produto existente sem índice: " + identifier(kind, row))
        else:
            if kind == "produtos" and db.get(INDEX, identifier(kind, row)):
                raise ValueError("Índice sem produto: " + identifier(kind, row))
            missing.append(row)
    if not dry_run:
        for row in missing:
            insert(kind, row)
    return {"source": len(rows), "existing": existing, "inserted": 0 if dry_run else len(missing), "pending": len(missing) if dry_run else 0}
