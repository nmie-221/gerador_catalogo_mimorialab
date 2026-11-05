"""DynamoDB persistence with paginated queries and optimistic concurrency."""
import time
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


@st.cache_resource(show_spinner=False)
def _connect(region, access_key_id, secret_access_key):
    # Creating a client costs hundreds of ms; reuse one per set of credentials.
    return boto3.client('dynamodb', region_name=region, aws_access_key_id=access_key_id,
                        aws_secret_access_key=secret_access_key,
                        config=Config(connect_timeout=5, read_timeout=10, retries={'max_attempts': 3}))


def _client():
    try:
        config = st.secrets['aws']
        return _connect(config['region'], config['access_key_id'], config['secret_access_key']), config['table_name']
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
            return StorageError('Acesso AWS negado. A aplicação precisa de GetItem, BatchGetItem, Query, PutItem e DeleteItem na tabela configurada. Veja docs/STREAMLIT_AWS.md.')
        if code in ['ProvisionedThroughputExceededException', 'ThrottlingException', 'RequestLimitExceeded']:
            return StorageError('O DynamoDB recusou a operação por limite de capacidade da tabela. Aguarde alguns segundos e tente de novo. '
                                'Para acabar com isso, mude a tabela para o modo sob demanda (veja docs/STREAMLIT_AWS.md).')
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


def transaction(items, token=None, deletes=()):
    """Atomically put items (with optimistic checks) and delete existing keys."""
    if len(items) + len(deletes) > 100:
        raise StorageError('Esta operação ultrapassa o limite de itens por transação.')
    try:
        client, table = _client()
        requests = [{'Put': {'TableName': table, **write_request(item, expected)}} for item, expected in items]
        requests += [{'Delete': {'TableName': table, 'Key': _encode({'PK': pk, 'SK': sk}),
                                 'ConditionExpression': 'attribute_exists(PK)'}} for pk, sk in deletes]
        args = dict(TransactItems=requests)
        if token:  # boto3 rejects None; only idempotent operations send a token.
            args['ClientRequestToken'] = token
        client.transact_write_items(**args)
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc


class BatchDenied(StorageError):
    pass


def batch_get(keys, fallback=True, consistent=True):
    """Read many (PK, SK) pairs, 100 per request, retrying unprocessed keys."""
    unique = list(dict.fromkeys((str(pk), str(sk)) for pk, sk in keys))
    found = {}
    try:
        client, table = _client()
        for start in range(0, len(unique), 100):
            pending = {table: {'Keys': [_encode({'PK': pk, 'SK': sk}) for pk, sk in unique[start:start + 100]],
                               'ConsistentRead': consistent}}
            for attempt in range(6):
                if attempt:
                    time.sleep(0.2 * 2 ** attempt)  # back off when capacity is exhausted
                response = client.batch_get_item(RequestItems=pending)
                for raw in response.get('Responses', {}).get(table, []):
                    item = _decode(raw)
                    found[(item['PK'], item['SK'])] = item
                pending = response.get('UnprocessedKeys') or {}
                if not pending:
                    break
            if pending:
                raise StorageError('O DynamoDB não retornou todos os registros. Tente novamente.')
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ['AccessDeniedException', 'AccessDenied']:
            raise _error(exc) from exc
        if not fallback:
            raise BatchDenied('A política AWS não permite dynamodb:BatchGetItem.') from exc
        # Policies created before BatchGetItem was needed still work, only slower.
        found = {}
        for pk, sk in unique:
            item = get(pk, sk)
            if item is not None:
                found[(pk, sk)] = item
    except BotoCoreError as exc:
        raise _error(exc) from exc
    return found


def delete(pk, sk):
    """Delete a record only if it exists."""
    try:
        client, table = _client()
        client.delete_item(TableName=table, Key=_encode({'PK': pk, 'SK': sk}),
                           ConditionExpression='attribute_exists(PK)')
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc


def delete_many(keys):
    """Atomically delete existing records, including catalog indexes."""
    try:
        client, table = _client()
        client.transact_write_items(TransactItems=[
            {'Delete': {'TableName': table, 'Key': _encode({'PK': pk, 'SK': sk}),
                        'ConditionExpression': 'attribute_exists(PK)'}}
            for pk, sk in keys
        ])
    except (ClientError, BotoCoreError) as exc:
        raise _error(exc) from exc
