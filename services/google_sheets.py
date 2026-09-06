from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SHEETS = {
    "produtos": "PRODUTOS",
    "variacoes": "VARIACOES",
    "categorias": "CATEGORIAS",
    "tamanhos": "TAMANHOS",
    "cores": "CORES",
    "materiais": "MATERIAIS",
}

HEADERS = {
    "PRODUTOS": ["id_produto", "nome_produto", "categoria_id", "abreviacao", "ativo", "data_cadastro"],
    "VARIACOES": ["sku", "id_produto", "tamanho_id", "cor_id", "quantidade_kit", "material_id", "preco", "custo", "ativo", "data_cadastro", "observacao"],
    "CATEGORIAS": ["id", "nome", "abreviacao", "ativo"],
    "TAMANHOS": ["id", "nome", "abreviacao", "ativo"],
    "CORES": ["id", "nome", "abreviacao", "ativo"],
    "MATERIAIS": ["id", "nome", "abreviacao", "ativo"],
}


class SheetsError(RuntimeError):
    """Erro amigavel de comunicacao ou configuracao da planilha."""


def _client() -> gspread.Client:
    try:
        credentials = Credentials.from_service_account_info(
            dict(st.secrets["google_service_account"]),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        return gspread.authorize(credentials)
    except Exception as exc:
        raise SheetsError("Nao foi possivel autenticar no Google Sheets. Verifique o st.secrets.") from exc


@st.cache_resource
def _spreadsheet() -> gspread.Spreadsheet:
    try:
        spreadsheet_id = str(st.secrets["google_sheets"]["spreadsheet_id"]).strip()
        if not spreadsheet_id:
            raise SheetsError("O ID da planilha nao foi configurado.")
        return _client().open_by_key(spreadsheet_id)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError("Nao foi possivel abrir a planilha configurada.") from exc


def _worksheet(name: str) -> gspread.Worksheet:
    try:
        return _spreadsheet().worksheet(name)
    except Exception as exc:
        raise SheetsError(f"A aba '{name}' nao foi encontrada na planilha.") from exc


@st.cache_data(ttl=30)
def read_sheet(name: str) -> pd.DataFrame:
    worksheet = _worksheet(name)
    try:
        values = worksheet.get_all_records()
    except Exception as exc:
        raise SheetsError(f"Nao foi possivel ler a aba '{name}'.") from exc
    return pd.DataFrame(values, columns=HEADERS.get(name, None))


def invalidate_cache() -> None:
    read_sheet.clear()
    _spreadsheet.clear()


def append_rows(name: str, rows: Iterable[Iterable[Any]]) -> None:
    values = [list(row) for row in rows]
    if not values:
        return
    try:
        _worksheet(name).append_rows(values, value_input_option="USER_ENTERED")
    except Exception as exc:
        raise SheetsError(f"Nao foi possivel inserir dados na aba '{name}'.") from exc
    invalidate_cache()


def update_row(name: str, row_number: int, values: Iterable[Any]) -> None:
    row_values = list(values)
    try:
        worksheet = _worksheet(name)
        worksheet.update(f"A{row_number}:{chr(64 + len(row_values))}{row_number}", [row_values])
    except Exception as exc:
        raise SheetsError(f"Nao foi possivel atualizar a aba '{name}'.") from exc
    invalidate_cache()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
