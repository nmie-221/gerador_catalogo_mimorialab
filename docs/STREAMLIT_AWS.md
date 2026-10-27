# Publicação das telas integradas

O arquivo principal continua sendo `app.py`. A branch de teste é `work`.

## Onde os dados ficam

- Google Sheets: produtos e cadastros auxiliares existentes, com o login atual.
- DynamoDB: matérias-primas, saldo e histórico de estoque, configuração da hora, perfis de impressão, ficha técnica e plataformas de cada produto.
- O botão Aplicar preço grava o preço escolhido e o custo completo no cadastro existente da planilha. É necessária confirmação.
- Não há importação automática das três abas experimentais de estoque. Os cadastros novos são feitos nas telas com persistência em DynamoDB.
- Não há uso de dados fictícios na aplicação principal.

## Secrets do aplicativo principal

O app principal precisa das seções Google Sheets e auth existentes e de `[aws]`, que pode ter sido configurada somente no aplicativo `aws_demo.py`. Configure as chaves exclusivamente no painel de Secrets do Streamlit, sem colocá-las no repositório.

```toml
[aws]
region = "sa-east-1"
table_name = "mimorialab-dev"
access_key_id = "PREENCHER_SOMENTE_NO_PAINEL_SEGURO"
secret_access_key = "PREENCHER_SOMENTE_NO_PAINEL_SEGURO"
```

Use uma chave válida do usuário dedicado à aplicação. Revogue as chaves que tenham entrado em commits. Nenhuma chave é incluída neste código.

## Permissões do usuário do Streamlit

A permissão GetItem usada no teste não permite salvar. Anexe a seguinte política ao usuário IAM da aplicação, substituindo o ID da conta (12 dígitos, sem hífens). Isso é separado da role OIDC do GitHub Actions.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:PutItem",
      "dynamodb:TransactWriteItems"
    ],
    "Resource": "arn:aws:dynamodb:sa-east-1:SEU_ID_DA_CONTA:table/mimorialab-dev"
  }]
}
```

As operações Put das transações também requerem PutItem. Não são necessários Scan, DeleteTable ou AdministratorAccess. Não altere a role de infraestrutura para autenticar a aplicação.

A tabela atual PK/SK atende aos novos registros; nenhuma mudança Terraform é necessária.

## Sequência de teste no Streamlit

1. Configure o app de teste para usar a branch `work` e o arquivo `app.py`, com os Secrets do app principal.
2. Faça login normalmente. Produtos e cadastros existentes devem continuar disponíveis.
3. Em Custos de produção, cadastre R$ 20/h e um perfil de impressão: R$ 120 / 600 lados + R$ 0,02 de manutenção + R$ 0,01 de energia = R$ 0,23/lado.
4. Em Matérias-primas e estoque, cadastre um material de teste: uma resma, 500 folhas por embalagem, R$ 35. Saldo começa em zero.
5. Registre a entrada de duas embalagens: saldo deve virar 1.000 folhas, custo por uso R$ 0,07.
6. Selecione um produto de teste em Ficha e preço. Adicione duas folhas, 15 minutos e dois lados impressos. Sem outros custos, o total será R$ 5,60.
7. Adicione plataformas ao produto. Comissão, tarifa e frete são próprios desse produto. Outro produto deve continuar sem as mesmas plataformas.
8. Confira preços e lucro. Comissão + margem de 100% ou mais deve bloquear a sugestão.
9. A aplicação de preço atualiza de verdade a planilha. Use produto de teste e confirme somente quando quiser essa alteração.
10. Registrar produção também movimenta estoque de verdade. Uma unidade do produto acima consome duas folhas.
11. Tente produzir além do saldo: nenhum material deve ser parcialmente consumido. Confira o histórico.
12. Atualize/reabra a sessão: valores salvos no DynamoDB devem continuar disponíveis.

## Regras e limites

- Último preço de compra, não custo médio, determina o custo por uso.
- Unidades e quantidade por embalagem ficam preservadas após cadastro; não há conversão automática.
- Compra: quantidade de embalagens × unidades por embalagem. Entrada atualiza o último preço.
- Ajustes e perdas usam a unidade de uso e preservam histórico; saldo negativo é bloqueado.
- Custo completo = materiais + hora × minutos/60 + perfil de impressão × lados + outros custos.
- Papel deve estar na ficha para não ser contado duas vezes no perfil de impressão.
- Cada plataforma possui comissão percentual, tarifa fixa e frete por produto. Não abatemos frete recebido do cliente.
- Preço = (custo completo + tarifa + frete)/(1 − comissão/100 − margem/100), arredondado para cima em centavos.
- O catálogo mantém um preço único aplicado; os diferentes preços sugeridos ficam na comparação.
- Atualizar a hora, os perfis ou o material altera as próximas simulações; preços já aplicados não mudam automaticamente.
- Transações do DynamoDB protegem o estoque contra baixas parciais. Versões evitam sobrescrever uma alteração concorrente; repetições da mesma operação não consomem estoque duas vezes.
- Máximo de 98 materiais por produção; cada documento do DynamoDB tem limite de 400 KB. Histórico usa registros separados.
- Registros de produção guardam o custo unitário calculado no momento.
- A gravação na planilha não faz parte da transação AWS. Não há transação distribuída nem migração automática do catálogo.

## Desenvolvimento e validação

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
streamlit run app.py
```

Os testes de DynamoDB usam Moto, com uma tabela AWS simulada. Eles não acessam a conta real. A publicação e as permissões reais devem ser verificadas no Streamlit após configurar o usuário IAM.
