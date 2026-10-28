from copy import deepcopy
from decimal import Decimal
import unittest
import os
from unittest.mock import patch
from uuid import uuid4
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

import boto3
from moto import mock_aws

from repositories import production as repo
from services import dynamodb as store
from utils.pricing import quote


class ProductionTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'AWS_PROFILE': 'default', 'AWS_DEFAULT_PROFILE': 'default'})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('AWS_PROFILE', None)
        os.environ.pop('AWS_DEFAULT_PROFILE', None)
        boto3.DEFAULT_SESSION = None
        self.aws = mock_aws()
        self.aws.start()
        self.addCleanup(self.aws.stop)
        self.client = boto3.client('dynamodb', region_name='sa-east-1', aws_access_key_id='test', aws_secret_access_key='test')
        self.client.create_table(TableName='mimorialab-test', KeySchema=[{'AttributeName': 'PK', 'KeyType': 'HASH'}, {'AttributeName': 'SK', 'KeyType': 'RANGE'}], AttributeDefinitions=[{'AttributeName': 'PK', 'AttributeType': 'S'}, {'AttributeName': 'SK', 'AttributeType': 'S'}], BillingMode='PAY_PER_REQUEST')
        self.connection = patch.object(store, '_client', return_value=(self.client, 'mimorialab-test'))
        self.connection.start()
        self.addCleanup(self.connection.stop)

    def add_material(self, name='Papel', stock=500):
        repo.save_material(dict(name=name, brand='Marca', pack='Resma', per=500, unit='folha', price=35, minimum=50, active=True, stock=0))
        m = next(m for m in repo.materials() if m['name'] == name)
        repo.move(m['SK'], 'Ajuste de entrada', stock, str(uuid4()), note='Saldo inicial')
        return store.get(repo.MATERIALS, m['SK'])

    def test_money_and_conservative_price(self):
        m = self.add_material()
        self.assertIsInstance(m['price'], Decimal)
        self.assertEqual(m['price']/m['per'], Decimal('.07'))
        result = quote(10, 10, 4, 12, 30)
        self.assertEqual(result['price'], Decimal('43.34'))
        self.assertGreaterEqual(result['margin'], 30)
        with self.assertRaises(ValueError):
            quote(10, 80, 0, 0, 30)

    def test_entry_conversion_and_idempotency(self):
        m = self.add_material()
        token = str(uuid4())
        repo.move(m['SK'], 'Entrada de compra', 2, token, price=40)
        repo.move(m['SK'], 'Entrada de compra', 2, token, price=40)
        current = store.get(repo.MATERIALS, m['SK'])
        self.assertEqual(current['stock'], 1500)
        self.assertEqual(current['price'], 40)
        before = len(store.query(repo.EVENTS))
        with self.assertRaises(ValueError):
            repo.move(m['SK'], 'Perda', 2000, str(uuid4()), note='Perda')
        self.assertEqual(len(store.query(repo.EVENTS)), before)

    def test_settings_and_product_isolation(self):
        config = repo.settings()
        config.update(hour_mode='monthly', monthly=2000, hours=100)
        config['prints'] = [dict(id='PRINT', name='Colorida', ink=120, **{'yield': 600}, maintenance=.02, energy=.01)]
        repo.save_settings(config)
        self.assertEqual(repo.hourly(repo.settings()), 20)
        self.assertEqual(repo.print_rate(repo.settings()['prints'][0]), Decimal('.23'))
        m = self.add_material()
        data = repo.product_costs('P001')
        data.update(recipe=[dict(material_id=m['SK'], quantity=2)], minutes=15, print_id='PRINT', prints=2, platforms=[dict(id='S', name='Shopee', commission=20, fixed=4, freight=6)])
        repo.save_product_costs(data)
        costs = repo.breakdown(repo.product_costs('P001'), repo.settings(), repo.materials())
        self.assertEqual(costs['total'], Decimal('5.60'))
        self.assertEqual(repo.product_costs('P002')['platforms'], [])
        self.assertEqual(len(repo.product_costs('P001')['platforms']), 1)
        stale = repo.product_costs('P001')
        repo.save_product_costs(stale)
        with self.assertRaises(store.ConflictError):
            repo.save_product_costs(stale)

    def test_production_all_or_nothing_and_repeat(self):
        a = self.add_material('Papel', 10)
        b = self.add_material('Fita', 1)
        data = repo.product_costs('P001')
        data['recipe'] = [dict(material_id=a['SK'], quantity=2), dict(material_id=b['SK'], quantity=1)]
        repo.save_product_costs(data)
        with self.assertRaises(ValueError):
            repo.produce('P001', 2, str(uuid4()))
        self.assertEqual(store.get(repo.MATERIALS, a['SK'])['stock'], 10)
        token = str(uuid4())
        repo.produce('P001', 1, token)
        repo.produce('P001', 1, token)
        self.assertEqual(store.get(repo.MATERIALS, a['SK'])['stock'], 8)
        self.assertEqual(store.get(repo.MATERIALS, b['SK'])['stock'], 0)
        event = store.get(repo.EVENTS, token)
        self.assertIn('unit_cost', event)
        self.assertEqual(len(event['consumed']), 2)

    def test_concurrent_stock_change_rejects_entire_transaction(self):
        m = self.add_material(stock=5)
        stale = deepcopy(m)
        repo.move(m['SK'], 'Perda', 1, str(uuid4()), note='Perda')
        stale.update(stock=0, revision=stale['revision']+1)
        token = str(uuid4())
        with self.assertRaises(store.ConflictError):
            store.transaction([(stale, m['revision']), (dict(PK=repo.EVENTS, SK=token), None)], token)
        self.assertEqual(store.get(repo.MATERIALS, m['SK'])['stock'], 4)
        self.assertIsNone(store.get(repo.EVENTS, token))

    def test_native_screens_and_platform_form_persistence(self):
        products = pd.DataFrame([dict(id_produto='P001', nome_produto='Teste', categoria='C1', tamanho='T1', cor='R1', material='M1', preco=20, custo=5, qtd_kit='K1', sku='SKU', codigo_barras='', imagem_url='')])
        def sheet(name):
            if name == 'PRODUTOS':
                return products
            return pd.DataFrame([dict(id='A1', nome='Opção', abreviacao='OP', ativo='Sim')])
        with patch('repositories.data.read_sheet', side_effect=sheet):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
            app.session_state['authenticated'] = True
            app.run(timeout=20)
            for page in ['🏠 Início', '📦 Matérias-primas e estoque', '⏱️ Custos de produção', '🧾 Ficha e preço', '🧩 Catálogos auxiliares', '🔎 Consultar Produtos']:
                nav = {'🏠 Início':'Início','📦 Matérias-primas e estoque':'Matérias-primas','⏱️ Custos de produção':'Custos de produção','🧾 Ficha e preço':'Ficha e preço','🧩 Catálogos auxiliares':'Cadastros','🔎 Consultar Produtos':'Produtos'}
                next(w for w in app.get('button_group') if w.key == 'main_navigation').set_value(nav[page]).run(timeout=20)
                self.assertFalse(app.exception, page)
            next(w for w in app.get('button_group') if w.key == 'main_navigation').set_value('Custos de produção').run()
            next(n for n in app.number_input if n.label == 'Valor da hora (R$)').set_value(25.)
            next(b for b in app.button if b.label == 'Salvar valor da hora').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['page'], '⏱️ Custos de produção')
            self.assertEqual(repo.hourly(repo.settings()), 25)
            self.assertTrue(any('Valor da hora salvo' in s.value for s in app.success))
            app.run()
            self.assertEqual(app.session_state['page'], '⏱️ Custos de produção')
            self.assertEqual(next(n for n in app.number_input if n.label == 'Valor da hora (R$)').value, 25.)
            next(w for w in app.get('button_group') if w.key == 'main_navigation').set_value('Ficha e preço').run()
            name = next(t for t in app.text_input if t.label == 'Nome da plataforma')
            name.set_value('Shopee teste')
            next(b for b in app.button if b.label == 'Adicionar plataforma').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(repo.product_costs('P001')['platforms'][0]['name'], 'Shopee teste')
            self.assertEqual(repo.product_costs('P002')['platforms'], [])
            self.assertTrue(any(b.label == 'Aplicar preço ao produto' for b in app.button))

    def ui_app(self):
        products = pd.DataFrame([dict(id_produto='P001', nome_produto='Teste', categoria='A1', tamanho='A1', cor='A1', material='A1', preco=20, custo=5, qtd_kit='A1', sku='SKU', codigo_barras='', imagem_url='')])
        def sheet(name):
            return products if name == 'PRODUTOS' else pd.DataFrame([dict(id='A1', nome='Opção', abreviacao='OP', ativo='Sim')])
        reader = patch('repositories.data.read_sheet', side_effect=sheet)
        reader.start()
        self.addCleanup(reader.stop)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'))
        app.session_state['authenticated'] = True
        return app.run(timeout=20)

    def navigate(self, app, label):
        next(w for w in app.get('button_group') if w.key == 'main_navigation').set_value(label).run()
        self.assertFalse(app.exception)

    def field(self, app, kind, label):
        return next(w for w in getattr(app, kind) if w.label == label)

    def click(self, app, label):
        self.field(app, 'button', label).click().run()
        self.assertFalse(app.exception)

    def test_hour_modes_print_profile_and_new_session(self):
        app = self.ui_app()
        self.navigate(app, 'Custos de produção')
        self.field(app, 'number_input', 'Valor da hora (R$)').set_value(27.)
        self.click(app, 'Salvar valor da hora')
        self.assertEqual(repo.hourly(repo.settings()), 27)
        self.assertEqual(app.session_state['_active_page'], '⏱️ Custos de produção')
        app.radio(key='costs_hour_mode').set_value('Calcular pela remuneração mensal').run()
        self.field(app, 'number_input', 'Remuneração mensal desejada (R$)').set_value(3000.)
        self.field(app, 'number_input', 'Horas produtivas por mês').set_value(100.)
        self.click(app, 'Salvar valor da hora')
        self.assertEqual(repo.hourly(repo.settings()), 30)
        self.assertTrue(any('Valor da hora salvo' in m.value for m in app.success))
        app.selectbox(key='costs_section').select('Custo por impressão').run()
        self.field(app, 'text_input', 'Nome do perfil / impressora').set_value('Impressora teste')
        self.field(app, 'number_input', 'Custo do conjunto de tinta ou toner (R$)').set_value(120.)
        self.field(app, 'number_input', 'Rendimento estimado em lados impressos').set_value(600)
        self.field(app, 'number_input', 'Manutenção por lado (R$)').set_value(.02)
        self.field(app, 'number_input', 'Energia por lado (R$)').set_value(.01)
        self.click(app, 'Salvar perfil')
        self.assertEqual(repo.print_rate(repo.settings()['prints'][0]), Decimal('.23'))
        self.assertEqual(app.session_state['page'], '⏱️ Custos de produção')
        self.assertEqual(app.selectbox(key='costs_section').value, 'Custo por impressão')
        # A separate Streamlit session must reload from DynamoDB, not session state.
        app = self.ui_app()
        self.navigate(app, 'Custos de produção')
        self.assertEqual(app.radio(key='costs_hour_mode').value, 'Calcular pela remuneração mensal')
        self.assertTrue(any(m.value == 'R$ 30,00' for m in app.metric))

    def test_material_entry_recipe_platform_price_and_production_forms(self):
        app = self.ui_app()
        self.navigate(app, 'Matérias-primas')
        next(w for w in app.get('button_group') if w.key == 'inventory_section').set_value('Cadastrar matéria-prima').run()
        self.field(app, 'text_input', 'Nome').set_value('Papel teste')
        self.field(app, 'text_input', 'Marca').set_value('Minha marca livre')
        self.field(app, 'number_input', 'Preço de uma embalagem (R$)').set_value(35.)
        self.click(app, 'Salvar matéria-prima')
        self.assertEqual(app.session_state['page'], '📦 Matérias-primas e estoque')
        self.assertEqual(repo.materials()[0]['brand'], 'Minha marca livre')
        mid = repo.materials()[0]['SK']
        next(w for w in app.get('button_group') if w.key == 'inventory_section').set_value('Registrar entrada').run()
        self.field(app, 'number_input', 'Embalagens compradas').set_value(2.)
        self.click(app, 'Confirmar movimentação')
        self.assertEqual(store.get(repo.MATERIALS, mid)['stock'], 1000)
        self.navigate(app, 'Ficha e preço')
        self.click(app, 'Adicionar à ficha')
        self.assertEqual(repo.product_costs('P001')['recipe'][0]['material_id'], mid)
        self.field(app, 'text_input', 'Nome da plataforma').set_value('Venda teste')
        self.field(app, 'number_input', 'Comissão máxima (%)').set_value(10.)
        self.click(app, 'Adicionar plataforma')
        self.assertEqual(len(repo.product_costs('P001')['platforms']), 1)
        self.field(app, 'checkbox', 'Confirmo atualizar o preço e o custo do produto no catálogo').check().run()
        with patch('views.production.update_row') as update:
            self.click(app, 'Aplicar preço ao produto')
        update.assert_called_once()
        self.assertEqual(app.session_state['page'], '🧾 Ficha e preço')
        self.field(app, 'checkbox', 'Confirmo a produção e a baixa dos materiais').check()
        self.click(app, 'Confirmar produção')
        self.assertEqual(store.get(repo.MATERIALS, mid)['stock'], 999)
        self.assertEqual(app.session_state['page'], '🧾 Ficha e preço')

    def test_save_failure_stays_on_form_and_displays_error(self):
        app = self.ui_app()
        self.navigate(app, 'Custos de produção')
        self.field(app, 'number_input', 'Valor da hora (R$)').set_value(40.)
        with patch('services.dynamodb.put', side_effect=store.StorageError('Sem permissão para gravar.')):
            self.click(app, 'Salvar valor da hora')
        self.assertEqual(app.session_state['_active_page'], '⏱️ Custos de produção')
        self.assertTrue(any('Sem permissão' in e.value for e in app.error))
        self.assertFalse(app.success)
        self.assertEqual(repo.hourly(repo.settings()), 0)
        # Clicking the selected navigation pill again must not navigate home.
        next(w for w in app.get('button_group') if w.key == 'main_navigation').set_value(None).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['_active_page'], '⏱️ Custos de produção')

    def test_material_suggestions_keep_custom_values_and_require_brand(self):
        from views.production import suggested_input
        with patch('views.production.st.selectbox', return_value='Minha marca') as select:
            self.assertEqual(suggested_input('Marca', ['Chamex'], ['Marca própria', 'chamex'], 'Marca própria'), 'Minha marca')
            self.assertEqual(select.call_args.args[1], ['Chamex', 'Marca própria'])
            self.assertTrue(select.call_args.kwargs['accept_new_options'])
            self.assertEqual(select.call_args.kwargs['index'], 1)
        with self.assertRaises(ValueError):
            repo.save_material(dict(name='Papel', brand=None, pack='Resma', per=500, unit='folha', price=35, minimum=0, active=True))
        self.assertEqual(repo.materials(), [])

    def test_query_reads_all_pages(self):
        for i in range(4):
            store.put(dict(PK='PAGED', SK=str(i), payload='x'*300000))
        self.assertEqual(len(store.query('PAGED')), 4)


if __name__ == '__main__':
    unittest.main()
