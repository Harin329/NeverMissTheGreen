import json
import os
import boto3

TABLE = os.environ.get("TABLE_NAME", "golf_shots")
API_KEY = os.environ.get("API_KEY", "")

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE)


def resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def check_auth(event):
    if not API_KEY:
        return True
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    qs = event.get("queryStringParameters") or {}
    return (headers.get("x-api-key") or qs.get("key")) == API_KEY


def lambda_handler(event, context):
    if not check_auth(event):
        return resp(401, {"error": "unauthorized"})

    qs = event.get("queryStringParameters") or {}
    ts = qs.get("ts")
    if not ts:
        try:
            body = json.loads(event.get("body") or "{}")
            ts = body.get("ts")
        except json.JSONDecodeError:
            ts = None
    if not ts:
        return resp(400, {"error": "need ts of the shot to delete"})

    existing = table.get_item(Key={"pk": "SHOT", "sk": ts}).get("Item")
    if not existing:
        return resp(404, {"error": "no shot with that ts", "ts": ts})

    table.delete_item(Key={"pk": "SHOT", "sk": ts})
    return resp(200, {"status": "deleted", "ts": ts})