from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SHEETS = {
    "produtos": "PRODUTOS",
    "categorias": "CATEGORIAS",
    "tamanhos": "TAMANHOS",
    "cores": "CORES",
    "materiais": "MATERIAIS",
    "kits": "KIT",
}

HEADERS = {
    "PRODUTOS": ["id_produto", "nome_produto", "categoria", "tamanho", "cor", "material", "preco", "custo", "qtd_kit", "sku", "codigo_barras"],
    "CATEGORIAS": ["id", "nome", "abreviacao", "ativo"],
    "TAMANHOS": ["id", "nome", "abreviacao", "ativo"],
    "CORES": ["id", "nome", "abreviacao", "ativo"],
    "MATERIAIS": ["id", "nome", "abreviacao", "ativo"],
    "KIT": ["id", "nome", "abreviacao", "ativo"],
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
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise SheetsError(
            "Planilha nao encontrada ou sem permissao. Confirme o spreadsheet_id e compartilhe a planilha com o client_email da Service Account."
        ) from exc
    except PermissionError as exc:
        raise SheetsError(
            "A Service Account foi autenticada, mas nao tem permissao para acessar esta planilha. Compartilhe a planilha com o client_email configurado."
        ) from exc
    except gspread.exceptions.APIError as exc:
        raise SheetsError(
            "A API do Google recusou a abertura da planilha. Confirme que a Google Sheets API esta habilitada e que a Service Account tem acesso."
        ) from exc
    except Exception as exc:
        raise SheetsError(
            "Nao foi possivel abrir a planilha. Verifique o formato do spreadsheet_id, as credenciais e o compartilhamento com a Service Account."
        ) from exc


def _worksheet(name: str) -> gspread.Worksheet:
    try:
        spreadsheet = _spreadsheet()
        worksheets = spreadsheet.worksheets()
        expected = " ".join(name.split()).casefold()
        for worksheet in worksheets:
            if " ".join(worksheet.title.split()).casefold() == expected:
                return worksheet
        available = ", ".join(worksheet.title for worksheet in worksheets)
        raise SheetsError(f"A aba '{name}' nao foi encontrada. Abas disponiveis: {available or 'nenhuma'}.")
    except SheetsError:
        raise
    except gspread.exceptions.APIError as exc:
        raise SheetsError("O Google Sheets recusou o acesso. Confirme o compartilhamento com o e-mail da Service Account.") from exc
    except Exception as exc:
        raise SheetsError("Nao foi possivel consultar as abas da planilha. Verifique o ID e o acesso da Service Account.") from exc


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


def delete_row(name: str, row_number: int) -> None:
    try:
        _worksheet(name).delete_rows(row_number)
    except Exception as exc:
        raise SheetsError(f"Nao foi possivel excluir o registro da aba '{name}'.") from exc
    invalidate_cache()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
