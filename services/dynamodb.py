"""DynamoDB persistence with paginated queries and optimistic concurrency."""
from decimal import Decimal

import boto3
from boto3.dynamodb.types import TypeSerializer, TypeDeserializer
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
import streamlit as st


class StorageError(RuntimeError):
    pass


class ConflictError(StorageError):
    pass


def _client():
    try:
        config = st.secrets['aws']
        return boto3.client('dynamodb', region_name=config['region'],
                            aws_access_key_id=config['access_key_id'],
                            aws_secret_access_key=config['secret_access_key'],
                            config=Config(connect_timeout=5, read_timeout=10, retries={'max_attempts': 3})), config['table_name']
    except (KeyError, FileNotFoundError) as exc:
        raise StorageError('Configure [aws] nos Secrets do aplicativo principal: region, table_name, access_key_id e secret_access_key.') from exc


def _encode(item):
    # boto3 does not accept Python floats as DynamoDB numbers.
    def native_value(value):
        if isinstance(value, float):
            return Decimal(str(value))
        if isinstance(value, dict):
            return {k: native_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [native_value(v) for v in value]
        return value
    native = native_value(item)
    return {key: TypeSerializer().serialize(value) for key, value in native.items()}


def _decode(item):
    return {key: TypeDeserializer().deserialize(value) for key, value in item.items()}


def _error(exc):
    if isinstance(exc, ClientError):
        code = exc.response['Error']['Code']
        if code in ['ConditionalCheckFailedException', 'TransactionCanceledException']:
            reasons = exc.response.get('CancellationReasons', [])
            if code == 'ConditionalCheckFailedException' or not reasons or any(r.get('Code') in ['ConditionalCheckFailed', 'TransactionConflict'] for r in reasons):
                return ConflictError('Os dados mudaram em outra sessão ou a operação já foi registrada. Atualize a tela antes de tentar novamente.')
        if code in ['AccessDeniedException', 'AccessDenied']:
            return StorageError('Acesso AWS negado. A aplicação precisa de GetItem, Query, PutItem e TransactWriteItems na tabela configurada. Veja docs/STREAMLIT_AWS.md.')
        if code == 'ResourceNotFoundException':
            return StorageError('Tabela DynamoDB não encontrada. Confira table_name e a região nos Secrets.')
    return StorageError('Não foi possível acessar o DynamoDB. Confira a conexão, os Secrets e as permissões.')


def get(pk, sk):
    try:
        client, table = _client()
        response = client.get_item(TableName=table, Key=_encode({'PK': pk, 'SK': sk}), ConsistentRead=True)
        return _decode(response['Item']) if 'Item' in response else None
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc


def query(pk):
    try:
        client, table = _client()
        args = dict(TableName=table, KeyConditionExpression='PK = :pk', ExpressionAttributeValues=_encode({':pk': pk}), ConsistentRead=True)
        items = []
        while True:
            response = client.query(**args)
            items.extend(_decode(item) for item in response.get('Items', []))
            if not response.get('LastEvaluatedKey'):
                return items
            args['ExclusiveStartKey'] = response['LastEvaluatedKey']
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc


def write_request(item, expected=None):
    result = {'Item': _encode(item)}
    if expected is None:
        result['ConditionExpression'] = 'attribute_not_exists(PK)'
    else:
        result.update(ConditionExpression='#revision = :revision', ExpressionAttributeNames={'#revision': 'revision'}, ExpressionAttributeValues=_encode({':revision': expected}))
    return result


def put(item, expected=None):
    try:
        client, table = _client()
        client.put_item(TableName=table, **write_request(item, expected))
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc


def transaction(items, token):
    if len(items) > 100:
        raise StorageError('Esta produção ultrapassa o limite de materiais por operação.')
    try:
        client, table = _client()
        client.transact_write_items(TransactItems=[{'Put': {'TableName': table, **write_request(item, expected)}} for item, expected in items], ClientRequestToken=token)
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc
