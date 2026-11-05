"""Catalog persistence in DynamoDB. No Google Sheets calls after cutover."""
from decimal import Decimal
import pandas as pd
import streamlit as st
from services import dynamodb as db
from services.google_sheets import SHEETS, HEADERS

INDEX = "MIMORIALAB#CATALOG#PRODUCTS"
DOMAINS = {k: "MIMORIALAB#CATALOG#" + k.upper() for k in SHEETS if k != "produtos"}


LEGACY_DOMAINS = {  # partitions written by an earlier version of the migration
    "categorias": "MIMORIALAB#CATALOG#CATEGORIES", "tamanhos": "MIMORIALAB#CATALOG#SIZES",
    "cores": "MIMORIALAB#CATALOG#COLORS", "materiais": "MIMORIALAB#CATALOG#MATERIALS", "kits": "MIMORIALAB#CATALOG#KITS",
}


def backend_setting():
    """Value of [catalog] backend, tolerating common placements in the Secrets."""
    for section in ("catalog", "aws"):
        value = st.secrets.get(section, {})
        if hasattr(value, "get") and value.get("backend"):
            return str(value.get("backend")).strip().lower()
    return str(st.secrets.get("backend", "sheets")).strip().lower()


def enabled():
    return backend_setting() == "dynamodb"


def diagnose(max_product=300):
    """Count records per partition the app reads, plus legacy/unindexed data."""
    report = {"Lista de produtos (" + INDEX + ")": len(db.query(INDEX))}
    for kind, pk in DOMAINS.items():
        report[kind + " (" + pk + ")"] = len(db.query(pk))
    legacy = {kind: len(db.query(pk)) for kind, pk in LEGACY_DOMAINS.items()}
    indexed = {item["SK"] for item in db.query(INDEX)}
    found = db.batch_get([key("produtos", f"P{i:03d}") for i in range(1, max_product + 1)])
    details = sorted(pk.rsplit("#", 1)[-1] for pk, _ in found)
    return dict(report=report, legacy=legacy, products=details, unindexed=[p for p in details if p not in indexed])


def repair():
    """Create missing product index entries and copy legacy domain partitions.

    Only inserts (conditional on the key not existing); never changes or deletes data.
    """
    result = diagnose()
    created = 0
    for pid in result["unindexed"]:
        try:
            db.put({"PK": INDEX, "SK": pid, "revision": 1})
            created += 1
        except db.ConflictError:
            pass
    for kind, pk in LEGACY_DOMAINS.items():
        for item in db.query(pk):
            copy = dict(item, PK=DOMAINS[kind], SK=str(item.get("id") or item["SK"]))
            copy.setdefault("id", copy["SK"])
            copy["revision"] = int(copy.get("revision", 1) or 1)
            try:
                db.put(copy)
                created += 1
            except db.ConflictError:
                pass
    return created


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
