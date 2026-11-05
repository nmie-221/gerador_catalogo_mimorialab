"""One-time migration screen: validate, preview and import Google Sheets catalog."""
import streamlit as st
from repositories import catalog_dynamo as catalog
from services.google_sheets import SHEETS, read_sheet
from services import dynamodb as db

KINDS = ("categorias", "tamanhos", "cores", "materiais", "kits", "produtos")


def migration_page():
    st.title("Migração do catálogo para DynamoDB")
    if catalog.enabled():
        st.success("O catálogo já está configurado para usar o DynamoDB.")
        diagnostics()
        st.divider()
        st.subheader("Importar da planilha o que ainda falta")
        st.caption("Importa apenas registros que não existem no DynamoDB. Nada que já está lá é alterado.")
        if not st.toggle("Mostrar importação da planilha", key="show_sheet_import"):
            return
    st.warning("Antes de migrar, interrompa edições no Google Sheets e faça uma cópia da planilha.")
    if not st.secrets.get("aws"):
        st.error("Configure os Secrets da AWS antes de continuar.")
        return
    try:
        # Columns added after the sheet was created come back empty, never NaN.
        frames = {kind: read_sheet(SHEETS[kind]).fillna("") for kind in KINDS}
        products = frames["produtos"]
        for kind in KINDS[:-1]:
            values = set(frames[kind]["id"].astype(str))
            field = {"categorias": "categoria", "tamanhos": "tamanho", "cores": "cor",
                     "materiais": "material", "kits": "qtd_kit"}[kind]
            missing = set(products[field].astype(str)) - values
            if missing:
                raise ValueError(f"Referências inexistentes em {kind}: {sorted(missing)}")
        results = {kind: catalog.import_sheet(kind, frames[kind], dry_run=True) for kind in KINDS}
    except Exception as exc:
        st.error(f"Validação não concluída: {exc}")
        return
    st.subheader("Prévia da importação")
    for kind, result in results.items():
        st.write(f"**{kind.title()}**: {result['source']} registros; {result['existing']} existentes; {result['pending']} pendentes.")
    st.caption("A importação não altera nem apaga os dados no Google Sheets.")
    confirm = st.checkbox("Confirmei o backup e interrompi as edições na planilha.")
    if st.button("Importar registros pendentes", disabled=not confirm, type="primary"):
        try:
            for kind in KINDS:
                catalog.import_sheet(kind, frames[kind], dry_run=False)
            verified = {kind: catalog.read(kind) for kind in KINDS}
            for kind in KINDS:
                # Records created in the app after the cutover may exist only in DynamoDB.
                field = "id_produto" if kind == "produtos" else "id"
                missing = set(frames[kind][field].astype(str)) - set(verified[kind][field].astype(str))
                if missing:
                    raise ValueError(f"IDs da planilha ausentes no DynamoDB em {kind}: {sorted(missing)}")
            st.session_state.pop("catalog_diagnosis", None)
            st.success("Importação concluída e IDs conferidos." + ("" if catalog.enabled() else " Ative [catalog] backend = 'dynamodb' nos Secrets e reinicie o app."))
        except (ValueError, db.StorageError) as exc:
            st.error(f"Importação interrompida: {exc}. Corrija e execute novamente; registros já gravados serão preservados.")


def diagnostics():
    st.subheader("Diagnóstico dos dados no DynamoDB")
    aws = st.secrets.get("aws", {})
    st.caption(f"Tabela: {aws.get('table_name', '?')} · Região: {aws.get('region', '?')}")
    if st.button("Executar diagnóstico"):
        st.session_state.pop("catalog_diagnosis", None)
        try:
            with st.spinner("Consultando o DynamoDB..."):
                st.session_state.catalog_diagnosis = catalog.diagnose()
        except db.StorageError as exc:
            st.error(str(exc))
            return
    result = st.session_state.get("catalog_diagnosis")
    if result is None:
        return
    st.write("**Registros encontrados nas chaves que o app lê:**")
    st.table({"Chave": list(result["report"]), "Registros": list(result["report"].values())})
    if result["products"] is None:
        st.warning("A política AWS ainda não tem dynamodb:BatchGetItem, então não foi possível procurar produtos fora da lista. "
                   "Inclua essa permissão (ela também deixa o app mais rápido) e execute de novo.")
    else:
        st.write(f"**Produtos encontrados (P001 a P060):** {len(result['products'])}"
                 + (f" · sem entrada na lista: {', '.join(result['unindexed'])}" if result["unindexed"] else ""))
    legacy = {k: v for k, v in result["legacy"].items() if v}
    if legacy:
        st.write("**Cadastros gravados no formato antigo (em inglês):** " + ", ".join(f"{k}: {v}" for k, v in legacy.items()))
    if result["unindexed"] or legacy:
        st.warning("Há dados que o app não enxerga. O reparo só cria as chaves que faltam; nada é alterado nem apagado.")
        if st.button("Reparar chaves", type="primary"):
            try:
                created = catalog.repair()
            except db.StorageError as exc:
                st.error(str(exc))
            else:
                st.session_state.pop("catalog_diagnosis", None)
                st.success(f"{created} chave(s) criada(s). Abra Produtos para conferir.")
    elif not any(result["report"].values()):
        st.error("Nenhum registro encontrado nas chaves conhecidas. Confira se table_name e region acima são os da tabela "
                 "onde você vê os dados e me envie o PK/SK de alguns itens.")
    else:
        st.info("As chaves estão consistentes.")
