"""Fiscal auxiliary tables (CFOP, CSOSN, origem) stored in DynamoDB.

The NCM is not here: it belongs to the product category (Cadastros > Categorias).

The code itself is the record key, so products store the plain code (for
example "5102") and the marketplaces receive exactly what is registered here.
Each table may mark one record as the default used for new products.
"""
from services import dynamodb as store

KINDS = {
    "cfop_estadual": dict(label="CFOP venda mesmo estado", field="cfop_estadual", digits=4, first="5",
                          default=("5102", "Venda de mercadoria adquirida ou recebida de terceiros")),
    "cfop_interestadual": dict(label="CFOP venda outros estados", field="cfop_interestadual", digits=4, first="6",
                               default=("6102", "Venda de mercadoria adquirida ou recebida de terceiros")),
    "csosn": dict(label="CSOSN", field="csosn", digits=3, first="",
                  default=("102", "Tributada pelo Simples Nacional sem permissão de crédito")),
    "origem": dict(label="Origem", field="origem", digits=1, first="",
                   default=("0", "Nacional, exceto as indicadas nos códigos 3, 4, 5 e 8")),
}


def partition(kind):
    if kind not in KINDS:
        raise ValueError("Cadastro fiscal inválido.")
    return "MIMORIALAB#FISCAL#" + kind.upper()


def normalize_code(kind, code):
    spec = KINDS[kind]
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digits) != spec["digits"] or len(digits) != len(str(code or "").replace(".", "").replace("-", "").strip()):
        raise ValueError(f"{spec['label']}: informe {spec['digits']} dígito(s) numérico(s).")
    if spec["first"] and not digits.startswith(spec["first"]):
        raise ValueError(f"{spec['label']}: o código deve começar com {spec['first']}.")
    if kind == "origem" and digits == "9":
        raise ValueError("Origem: use um código de 0 a 8.")
    return digits


def display_code(kind, code):
    return str(code or "")


def label(kind, record):
    return f"{display_code(kind, record['codigo'])} - {record['descricao']}"


def items(kind):
    """All records of a table; the documented default is created on first use."""
    records = store.query(partition(kind))
    default = KINDS[kind]["default"]
    if not records and default:
        code, description = default
        record = dict(PK=partition(kind), SK=code, codigo=code, descricao=description, padrao=True, ativo=True, revision=1)
        try:
            store.put(record)
        except store.ConflictError:
            pass  # another session seeded it first
        records = store.query(partition(kind))
    return sorted(records, key=lambda r: r["codigo"])


def default_code(records):
    return next((r["codigo"] for r in records if r.get("padrao") and r.get("ativo")), "")


def save(kind, code, description, is_default, active, previous=None):
    """Create (previous=None) or edit a record. The code of an existing record is immutable."""
    description = " ".join(str(description or "").split())
    if not description:
        raise ValueError("Informe a descrição.")
    records = items(kind)
    if previous is None:
        code = normalize_code(kind, code)
        if any(r["codigo"] == code for r in records):
            raise ValueError("Este código já está cadastrado.")
        item = dict(PK=partition(kind), SK=code, codigo=code, descricao=description, padrao=bool(is_default), ativo=bool(active), revision=1)
        writes = [(item, None)]
    else:
        current = next((r for r in records if r["codigo"] == previous["codigo"]), None)
        if current is None or current["revision"] != previous["revision"]:
            raise store.ConflictError("Registro alterado em outra sessão. Atualize a página.")
        item = dict(current, descricao=description, padrao=bool(is_default), ativo=bool(active), revision=current["revision"] + 1)
        writes = [(item, current["revision"])]
    if item["padrao"] and not item["ativo"]:
        raise ValueError("O código padrão precisa estar ativo.")
    if item["padrao"]:
        # Only one default per table: unset the previous one in the same transaction.
        for other in records:
            if other["codigo"] != item["codigo"] and other.get("padrao"):
                writes.append((dict(other, padrao=False, revision=other["revision"] + 1), other["revision"]))
    store.transaction(writes)
    return item


def delete(kind, code, in_use):
    if in_use:
        raise ValueError("Este código está vinculado a produtos. Desative-o em vez de excluir.")
    store.delete(partition(kind), str(code))
