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
PRODUTOS: id_produto, nome_produto, categoria, tamanho, cor, material, preco, custo, qtd_kit, sku, codigo_barras, imagem_url, cfop_estadual, cfop_interestadual, csosn, origem, peso_liquido_g, peso_bruto_g, altura_cm, largura_cm, comprimento_cm, sob_encomenda, dias_producao
CATEGORIAS: id, nome, abreviacao, ativo, ncm
TAMANHOS/CORES/MATERIAIS/KIT: id, nome, abreviacao, ativo
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

Produtos, domínios e SKUs são validados sem diferenciar maiúsculas/minúsculas ou espaços extras. O SKU é montado automaticamente sem hífens, concatenando `NUMERO_ID+CATEGORIA+TAMANHO+COR+KIT+MATERIAL` (por exemplo, `001AD5X5BRK2VF`). Cada abreviação deve ter de 1 a 4 letras ou números; não há limite total de caracteres para o SKU. Preço e custo são lidos como valores reais, e preço zero resulta em margem de 0%, evitando divisão por zero. O cache é invalidado após cada escrita.

## Exclusão e edição

Produtos podem ser editados e excluídos diretamente na tela **Produtos**. A exclusão remove a linha da aba `PRODUTOS`, conforme o novo modelo da planilha.

## Cadastro de produto em uma única tela

**Produtos › Cadastrar** e **Produtos › Editar** usam a mesma tela, com abas:

- **Identificação**: nome, categoria, tamanho, cor, material, kit e imagem. O SKU continua automático.
- **Ficha técnica (custo)**: matérias-primas consumidas por unidade, tempo de mão de obra, impressão e outros custos (embalagem, brinde etc.). Dá para cadastrar uma matéria-prima nova ali mesmo, já incluída na ficha.
- **Preço e plataformas**: taxas de cada plataforma (iniciadas com as taxas padrão de *Custos de produção*), custo total, lucro e margem no preço atual e o preço sugerido para a margem desejada.
- **Fiscal**: CFOP mesmo estado (padrão 5102), CFOP outros estados (padrão 6102), CSOSN (padrão 102) e origem (padrão 0). O **NCM vem da categoria**.
- **Envio e prazo**: peso líquido, peso bruto com embalagem, dimensões do pacote e dias de produção para produtos sob encomenda.

O custo do produto é sempre a soma da ficha técnica. Ele é recalculado quando o preço de uma matéria-prima muda. O produto e a ficha são salvos juntos, numa única transação do DynamoDB. Produtos antigos que só tinham o custo digitado recebem esse valor como uma linha "Custo informado anteriormente" na ficha, para não perderem o custo nem o contarem duas vezes.

O código de barras saiu da tela. Valores já gravados são preservados.

## Produção

A tela **Produção** registra o que foi produzido e dá baixa nas matérias-primas da ficha técnica, numa única transação. Antes de confirmar, ela mostra quanto de cada material será consumido e quantas unidades dá para produzir com o estoque atual. Não existe estoque de produtos prontos. O histórico guarda a data, a quantidade, o custo unitário da produção e os materiais consumidos.

## Cadastros fiscais

Em **Cadastros › Fiscal** ficam as tabelas de CFOP, CSOSN e origem (no DynamoDB). Cada tabela tem um código padrão, sugerido em novos produtos. O NCM é informado em cada categoria. Confirme os códigos com sua contabilidade.

## Logotipo

Coloque o arquivo da sua marca em:

```text
assets/logo.png
```

O logotipo será exibido automaticamente no topo da barra lateral. PNG com fundo transparente é recomendado. Para usar outro formato, altere o nome do arquivo e a extensão na variável `logo_path` em `app.py`.
