# Gerador de catálogo MimoriaLab

Aplicação Streamlit para cadastro de produtos e variações comerciais usando uma planilha do Google Sheets como banco de dados.

## Arquitetura

- `app.py`: navegação e telas em português.
- `services/google_sheets.py`: autenticação, leitura, escrita em lote e cache.
- `repositories/data.py`: regras de negócio, unicidade, IDs, SKU e catálogo.
- `utils/`: normalização, validação e composição de SKU.

## Configuração do Google Sheets

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/), habilite a **Google Sheets API** e crie uma Service Account.
2. Gere uma chave JSON para a Service Account. Não a versione.
3. Crie uma planilha e compartilhe-a com o `client_email` da Service Account como Editor.
4. Crie as abas `PRODUTOS`, `VARIACOES`, `CATEGORIAS`, `TAMANHOS`, `CORES` e `MATERIAIS`.
5. Use a primeira linha de cada aba como cabeçalho:

```text
PRODUTOS: id_produto, nome_produto, categoria_id, abreviacao, ativo, data_cadastro
VARIACOES: sku, id_produto, tamanho_id, cor_id, quantidade_kit, material_id, preco, custo, ativo, data_cadastro, observacao
CATEGORIAS/TAMANHOS/CORES/MATERIAIS: id, nome, abreviacao, ativo
```

6. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`, preenchendo o ID da planilha e os campos da chave JSON.

## Execução local

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Community Cloud

Publique o repositório, selecione `app.py` como arquivo principal e cole o conteúdo do `secrets.toml` em **Settings > Secrets**. A Service Account deve continuar compartilhando a planilha.

Produtos, domínios e SKUs são validados sem diferenciar maiúsculas/minúsculas ou espaços extras. Variações em lote exibem uma prévia e gravam somente SKUs novos. Preço zero resulta em margem de 0%, evitando divisão por zero. O cache é invalidado após cada escrita.
