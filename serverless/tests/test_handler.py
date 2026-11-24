"""Тести Lambda-обробника з емуляцією DynamoDB через moto."""
import importlib
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))


def event(method, resource, farm_id=None, body=None):
    path = "/farms" + (f"/{farm_id}" if farm_id else "")
    return {
        "httpMethod": method,
        "resource": resource,
        "path": path,
        "pathParameters": {"id": farm_id} if farm_id else None,
        "body": body,
        "isBase64Encoded": False,
    }


@pytest.fixture
def h(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="farms",
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        import handler
        importlib.reload(handler)
        yield handler


def call(h, *a, **kw):
    r = h.handler(event(*a, **kw), None)
    return r["statusCode"], (json.loads(r["body"]) if r["body"] else None)


def test_crud(h):
    body = json.dumps({"name": " Зелена долина ", "region": "Чернівецька", "area_ha": 120.5})
    code, farm = call(h, "POST", "/farms", body=body)
    assert code == 201 and farm["name"] == "Зелена долина" and farm["area_ha"] == 120.5
    call(h, "POST", "/farms", body='{"name": "Друга", "area_ha": 7}')
    code, lst = call(h, "GET", "/farms")
    assert code == 200 and lst["count"] == 2
    code, got = call(h, "GET", "/farms/{id}", farm["id"])
    assert code == 200 and got == farm
    assert call(h, "DELETE", "/farms/{id}", farm["id"]) == (204, None)
    assert call(h, "GET", "/farms/{id}", farm["id"])[0] == 404
    assert call(h, "DELETE", "/farms/{id}", farm["id"])[0] == 404


@pytest.mark.parametrize("body", ['не JSON', '[1]', '{}', '{"name": ""}', '{"name": 5}',
                                  '{"name": "x", "area_ha": -1}', '{"name": "x", "area_ha": "big"}',
                                  '{"name": "x", "area_ha": true}', '{"name": "x", "region": 3}', None])
def test_validation(h, body):
    assert call(h, "POST", "/farms", body=body)[0] == 400


def test_routing(h):
    assert call(h, "PUT", "/farms")[0] == 405
    assert call(h, "PATCH", "/farms/{id}", "abc")[0] == 405
    assert call(h, "GET", "/other")[0] == 404
