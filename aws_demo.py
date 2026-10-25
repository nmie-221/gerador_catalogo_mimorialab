"""Read only a fictitious DynamoDB item to validate the AWS integration."""
import boto3
import streamlit as st
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

st.set_page_config(page_title="Teste AWS — MimoriaLab", page_icon="☁️")
st.title("Teste de conexão com o DynamoDB")
st.caption("Este teste apenas lê o registro fictício TESTE#CONEXAO. Não altera dados.")

if st.button("Testar conexão", type="primary"):
    try:
        settings = st.secrets["aws"]
        table = boto3.resource(
            "dynamodb",
            region_name=settings["region"],
            aws_access_key_id=settings["access_key_id"],
            aws_secret_access_key=settings["secret_access_key"],
            config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}),
        ).Table(settings["table_name"])
        with st.spinner("Consultando o registro de teste…"):
            response = table.get_item(
                Key={"PK": "TESTE#CONEXAO", "SK": "CADASTRO"},
                ConsistentRead=True,
            )
        item = response.get("Item")
        if item and item.get("mensagem") == "Conexão funcionando":
            st.success("Conexão funcionando: registro fictício lido com sucesso.")
        elif item:
            st.warning("Conectou, mas o registro não contém a mensagem de teste esperada.")
        else:
            st.warning("Conectou, mas o registro fictício não foi encontrado. Confira PK e SK na tabela.")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ErroAWS")
        messages = {
            "AccessDeniedException": "Acesso negado. Confira a permissão dynamodb:GetItem para esta tabela.",
            "ResourceNotFoundException": "Tabela não encontrada. Confira table_name e a região sa-east-1 nos Secrets.",
            "UnrecognizedClientException": "Credenciais não reconhecidas. Confira as chaves nos Secrets.",
            "ProvisionedThroughputExceededException": "Capacidade temporariamente excedida. Aguarde e tente novamente.",
        }
        st.error(messages.get(code, "A AWS recusou a consulta. Confira as credenciais e a configuração da tabela."))
    except (KeyError, FileNotFoundError):
        st.error("Configure [aws] nos Secrets com region, table_name, access_key_id e secret_access_key.")
    except BotoCoreError:
        st.error("Não foi possível conectar à AWS. Confira a configuração e tente novamente.")
