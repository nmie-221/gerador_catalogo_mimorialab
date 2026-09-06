from __future__ import annotations

import hmac

import streamlit as st


def _credentials() -> tuple[str, str]:
    try:
        auth = st.secrets["auth"]
        username = str(auth["username"]).strip()
        password = str(auth["password"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("Configure [auth] com username e password no st.secrets.") from exc
    if not username or not password:
        raise RuntimeError("As credenciais de login nao podem estar vazias.")
    return username, password


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated", False))


def login_screen() -> bool:
    st.title("Login")
    st.caption("Entre com suas credenciais para acessar o catálogo.")
    with st.form("login"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar", type="primary")
    if submitted:
        try:
            expected_username, expected_password = _credentials()
            valid = hmac.compare_digest(username.strip(), expected_username) and hmac.compare_digest(password, expected_password)
        except RuntimeError as exc:
            st.error(str(exc))
            return False
        if valid:
            st.session_state.authenticated = True
            st.rerun()
        st.error("Usuário ou senha inválidos.")
    return False


def logout() -> None:
    st.session_state.authenticated = False
    st.rerun()
