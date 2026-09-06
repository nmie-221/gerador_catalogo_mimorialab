# Gerador de catálogo MimoriaLab

Aplicação Streamlit para cadastro de produtos usando uma planilha do Google Sheets como banco de dados.

## Arquitetura

- `app.py`: navegação e telas em português.
- `services/google_sheets.py`: autenticação, leitura, escrita em lote e cache.
- `repositories/data.py`: regras de negócio, unicidade, IDs, SKU e catálogo.
- `utils/`: normalização, validação e composição de SKU.

## Configuração do Google Sheets

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/), habilite a **Google Sheets API** e crie uma Service Account.
2. Gere uma chave JSON para a Service Account. Não a versione.
3. Crie uma planilha e compartilhe-a com o `client_email` da Service Account como Editor.
4. Crie as abas `PRODUTOS`, `CATEGORIAS`, `TAMANHOS`, `CORES`, `MATERIAIS` e `KIT`.
5. Use a primeira linha de cada aba como cabeçalho:

```text
PRODUTOS: id_produto, nome_produto, categoria, tamanho, cor, material, preco, custo, qtd_kit, sku, codigo_barras
CATEGORIAS/TAMANHOS/CORES/MATERIAIS/KIT: id, nome, abreviacao, ativo
```

6. Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`, preenchendo o ID da planilha e os campos da chave JSON.
7. Preencha também a seção `[auth]` com o usuário e a senha que serão usados na tela de login. O arquivo `secrets.toml` não deve ser commitado.

Os nomes das abas são comparados ignorando espaços extras e diferenças entre maiúsculas e minúsculas. Se uma aba não for encontrada, a aplicação informa a lista de abas que a Service Account conseguiu enxergar; isso ajuda a confirmar se o ID da planilha e o compartilhamento estão corretos.

## Execução local

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Login

A aplicação exige login antes de exibir o catálogo. As credenciais ficam no `st.secrets`:

```toml
[auth]
username = "seu-usuario"
password = "uma-senha-forte"
```

O login é mantido apenas na sessão atual do Streamlit. Use o botão **Sair** na barra lateral para encerrar a sessão.

## Streamlit Community Cloud

Publique o repositório, selecione `app.py` como arquivo principal e cole o conteúdo do `secrets.toml` em **Settings > Secrets**. A Service Account deve continuar compartilhando a planilha.

Produtos, domínios e SKUs são validados sem diferenciar maiúsculas/minúsculas ou espaços extras. O SKU é montado automaticamente como `NUMERO_ID-CATEGORIA-TAMANHO-COR-KIT-MATERIAL` (por exemplo, `001-AD-5X5-BR-K2-VF`) e não pode ultrapassar 15 caracteres. Preço zero resulta em margem de 0%, evitando divisão por zero. O cache é invalidado após cada escrita.

## Exclusão e edição

Produtos podem ser editados e excluídos diretamente na tela **Produtos**. A exclusão remove a linha da aba `PRODUTOS`, conforme o novo modelo da planilha.
