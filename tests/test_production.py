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
                nav = {'🏠 Início':'⌂ Início','📦 Matérias-primas e estoque':'▧ Matérias-primas','⏱️ Custos de produção':'◷ Custos de produção','🧾 Ficha e preço':'☷ Ficha e preço','🧩 Catálogos auxiliares':'⚙ Cadastros','🔎 Consultar Produtos':'◇ Produtos'}
                app.radio(key='main_navigation').set_value(nav[page]).run(timeout=20)
                self.assertFalse(app.exception, page)
            app.radio(key='main_navigation').set_value('☷ Ficha e preço').run()
            name = next(t for t in app.text_input if t.label == 'Nome da plataforma')
            name.set_value('Shopee teste')
            next(b for b in app.button if b.label == 'Adicionar plataforma').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(repo.product_costs('P001')['platforms'][0]['name'], 'Shopee teste')
            self.assertEqual(repo.product_costs('P002')['platforms'], [])
            self.assertTrue(any(b.label == 'Aplicar preço ao produto' for b in app.button))

    def test_query_reads_all_pages(self):
        for i in range(4):
            store.put(dict(PK='PAGED', SK=str(i), payload='x'*300000))
        self.assertEqual(len(store.query('PAGED')), 4)


if __name__ == '__main__':
    unittest.main()
