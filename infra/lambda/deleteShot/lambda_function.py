import json
import os

import boto3

TABLE = os.environ.get("TABLE_NAME", "golf_shots")

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


def lambda_handler(event, context):
    # the JWT authorizer has already verified the token; the item key is
    # built from the caller's own user id, so others' shots are unreachable
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub = claims["sub"]

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

    key = {"pk": f"USER#{sub}", "sk": f"SHOT#{ts}"}
    existing = table.get_item(Key=key).get("Item")
    if not existing:
        return resp(404, {"error": "no shot with that ts", "ts": ts})

    table.delete_item(Key=key)
    return resp(200, {"status": "deleted", "ts": ts})
