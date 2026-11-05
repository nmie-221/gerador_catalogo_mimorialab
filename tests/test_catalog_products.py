"""Product + recipe persistence in DynamoDB, NCM per category and fiscal tables."""
import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import boto3
from moto import mock_aws

from repositories import catalog_dynamo, data, fiscal, production as repo
from services import dynamodb as store


class DynamoCase(unittest.TestCase):
    def setUp(self):
        for name in ('AWS_PROFILE', 'AWS_DEFAULT_PROFILE'):
            os.environ.pop(name, None)
        boto3.DEFAULT_SESSION = None
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        client = boto3.client('dynamodb', region_name='sa-east-1', aws_access_key_id='test', aws_secret_access_key='test')
        client.create_table(TableName='t', KeySchema=[{'AttributeName': 'PK', 'KeyType': 'HASH'}, {'AttributeName': 'SK', 'KeyType': 'RANGE'}],
                            AttributeDefinitions=[{'AttributeName': 'PK', 'AttributeType': 'S'}, {'AttributeName': 'SK', 'AttributeType': 'S'}],
                            BillingMode='PAY_PER_REQUEST')
        for target in [patch.object(store, '_client', return_value=(client, 't')), patch.object(catalog_dynamo, 'enabled', return_value=True)]:
            target.start()
            self.addCleanup(target.stop)
        for kind in ['categorias', 'tamanhos', 'cores', 'materiais', 'kits']:
            data.add_domain(kind, 'Opção', 'OP', True, '4820.10.00')
        repo.save_material(dict(name='Papel', brand='B', pack='Resma', per=500, unit='folha', price=35, minimum=0, stock=0, active=True))
        self.material = repo.materials()[0]['SK']

    def values(self, **extra):
        base = dict(nome_produto='Caderno', categoria='CAT001', tamanho='TAM001', cor='COR001', material='MAT001', qtd_kit='KIT001',
                    preco='25,00', imagem_url='', cfop_estadual='5102', cfop_interestadual='6102', csosn='102', origem='0',
                    peso_liquido_g=100, peso_bruto_g=150, altura_cm=2, largura_cm=15, comprimento_cm=21,
                    sob_encomenda=True, dias_producao=5)
        return {**base, **extra}

    def costs(self, **extra):
        return dict(repo.empty_costs(None), recipe=[dict(material_id=self.material, quantity=10)],
                    extras=[dict(name='Embalagem', value=1.5), dict(name='', value=0)], **extra)



class CatalogProductTests(DynamoCase):
    def test_product_and_recipe_saved_together_with_cost_from_recipe(self):
        pid, sku = data.save_product(None, self.values(), self.costs())
        self.assertEqual((pid, sku), ('P001', '001OPOPOPOPOP'))
        product = data.table('produtos').iloc[0]
        self.assertAlmostEqual(float(product['custo']), 2.2)  # 10 folhas * 0,07 + 1,50
        self.assertEqual(product['dias_producao'], 5)
        self.assertEqual(product['sob_encomenda'], 'Sim')
        recipe = repo.product_costs('P001')
        self.assertEqual(recipe['extras'], [dict(name='Embalagem', value=Decimal('1.5'))])
        self.assertEqual(data.catalog().iloc[0]['NCM'], '4820.10.00')
        # A material price change is reflected in the live cost.
        material = repo.materials()[0]
        material['price'] = 70
        repo.save_material(material)
        self.assertAlmostEqual(float(data.table('produtos').iloc[0]['custo']), 2.9)

    def test_failed_recipe_write_does_not_save_product(self):
        with patch.object(repo, 'materials', side_effect=[[], []]):
            with self.assertRaises(ValueError):
                data.save_product(None, self.values(), self.costs())
        self.assertTrue(data.table('produtos').empty)

    def test_stale_recipe_edit_is_rejected_atomically(self):
        data.save_product(None, self.values(), self.costs())
        stale = repo.product_costs('P001')
        data.save_product('P001', self.values(preco='30'), stale)
        with self.assertRaises(store.ConflictError):
            data.save_product('P001', self.values(preco='99'), stale)
        self.assertEqual(float(data.table('produtos').iloc[0]['preco']), 30)

    def test_validation_of_shipping_fields(self):
        with self.assertRaises(ValueError):
            data.save_product(None, self.values(peso_liquido_g=200), self.costs())
        with self.assertRaises(ValueError):
            data.save_product(None, self.values(dias_producao=0), self.costs())
        self.assertTrue(data.table('produtos').empty)

    def test_delete_removes_recipe_and_is_blocked_after_production(self):
        data.save_product(None, self.values(), self.costs())
        data.delete_product('P001')
        self.assertTrue(data.table('produtos').empty)
        self.assertEqual(repo.product_costs('P001')['revision'], 0)
        data.save_product(None, self.values(), self.costs())
        repo.move(self.material, 'Ajuste de entrada', 100, str(uuid4()), note='Saldo')
        repo.produce('P001', 1, str(uuid4()), 'Caderno')
        with self.assertRaises(ValueError):
            data.delete_product('P001')

    def test_category_ncm_validation(self):
        with self.assertRaises(ValueError):
            data.add_domain('categorias', 'Outra', 'OT', True, '1234')
        data.edit_domain('categorias', 'CAT001', 'Opção', 'OP', True, '')
        self.assertEqual(data.table('categorias').iloc[0]['ncm'], '')

    def test_production_plan_and_limit(self):
        data.save_product(None, self.values(), self.costs())
        repo.move(self.material, 'Ajuste de entrada', 35, str(uuid4()), note='Saldo')
        plan = repo.production_plan('P001', 4)
        self.assertFalse(plan[0]['ok'])
        self.assertEqual(repo.max_producible(plan), 3)

    def test_diagnose_and_repair_unindexed_products_and_legacy_domains(self):
        data.save_product(None, self.values(), self.costs())
        store.put(dict(PK='MIMORIALAB#PRODUCT#P002', SK='DETAILS', revision=1, id_produto='P002', nome_produto='Solto', sku='X2'))
        store.put(dict(PK='MIMORIALAB#CATALOG#COLORS', SK='COR009', id='COR009', nome='Azul', abreviacao='AZ', ativo='Sim', revision=1))
        result = catalog_dynamo.diagnose(5)
        self.assertEqual(result['unindexed'], ['P002'])
        self.assertEqual(result['legacy']['cores'], 1)
        self.assertEqual(catalog_dynamo.repair(), 2)
        self.assertEqual(catalog_dynamo.repair(), 0)  # idempotent
        self.assertEqual(sorted(data.table('produtos')['id_produto']), ['P001', 'P002'])
        self.assertIn('COR009', set(data.table('cores')['id']))


class FiscalTests(DynamoCase):
    def test_defaults_are_seeded_and_single(self):
        self.assertEqual(fiscal.default_code(fiscal.items('cfop_estadual')), '5102')
        self.assertEqual(fiscal.default_code(fiscal.items('cfop_interestadual')), '6102')
        self.assertEqual(fiscal.default_code(fiscal.items('csosn')), '102')
        self.assertEqual(fiscal.default_code(fiscal.items('origem')), '0')
        fiscal.save('cfop_estadual', '5101', 'Venda de produção do estabelecimento', True, True)
        records = fiscal.items('cfop_estadual')
        self.assertEqual([r['codigo'] for r in records if r['padrao']], ['5101'])

    def test_code_validation_and_duplicates(self):
        for kind, code in [('cfop_estadual', '6102'), ('cfop_interestadual', '5102'), ('csosn', '12'), ('origem', '9')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                fiscal.save(kind, code, 'X', False, True)
        with self.assertRaises(ValueError):
            fiscal.save('csosn', '102', 'Duplicado', False, True)

    def test_batch_get_reads_more_than_one_page(self):
        for i in range(120):
            store.put(dict(PK='B', SK=str(i)))
        found = store.batch_get([('B', str(i)) for i in range(120)] + [('B', 'missing')])
        self.assertEqual(len(found), 120)


if __name__ == '__main__':
    unittest.main()
