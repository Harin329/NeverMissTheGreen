import hashlib
import json
import os
import secrets
import time

import boto3
from boto3.dynamodb.conditions import Key

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
    # the JWT authorizer has already verified the token; claims are trusted
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub = claims["sub"]
    email = claims.get("email", "")
    user_name = email.split("@")[0] if email else sub[:8]
    method = event["requestContext"]["http"]["method"]

    if method == "POST":
        try:
            body = json.loads(event.get("body") or "{}")
        except json.JSONDecodeError:
            return resp(400, {"error": "invalid JSON"})
        label = str(body.get("label") or "Device key")[:60]

        plaintext = "nmg_" + secrets.token_urlsafe(24)
        h = hashlib.sha256(plaintext.encode()).hexdigest()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # lookup record for trackShot (key hash -> user)
        table.put_item(Item={
            "pk": f"KEY#{h}", "sk": "KEY",
            "userId": sub, "userName": user_name,
            "label": label, "created": now,
        })
        # mirror under the user so their keys can be listed/revoked
        table.put_item(Item={
            "pk": f"USER#{sub}", "sk": f"KEY#{h}",
            "label": label, "created": now, "last4": plaintext[-4:],
        })
        return resp(200, {"key": plaintext, "id": h, "label": label, "created": now})

    if method == "GET":
        page = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{sub}") & Key("sk").begins_with("KEY#")
        )
        keys = [
            {
                "id": it["sk"][4:],
                "label": it.get("label", ""),
                "created": it.get("created", ""),
                "last4": it.get("last4", ""),
            }
            for it in page.get("Items", [])
        ]
        return resp(200, {"keys": keys})

    if method == "DELETE":
        qs = event.get("queryStringParameters") or {}
        kid = qs.get("id")
        if not kid:
            return resp(400, {"error": "need id"})
        # the mirror row proves ownership; never delete another user's key
        mirror = table.get_item(Key={"pk": f"USER#{sub}", "sk": f"KEY#{kid}"}).get("Item")
        if not mirror:
            return resp(404, {"error": "no such key"})
        table.delete_item(Key={"pk": f"KEY#{kid}", "sk": "KEY"})
        table.delete_item(Key={"pk": f"USER#{sub}", "sk": f"KEY#{kid}"})
        return resp(200, {"status": "revoked", "id": kid})

    return resp(405, {"error": "method not allowed"})
