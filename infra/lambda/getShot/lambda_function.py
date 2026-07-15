import json
import os

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

    items = []
    kwargs = {
        "IndexName": "AllShots",
        "KeyConditionExpression": Key("gsi1pk").eq("SHOT"),
        "ScanIndexForward": True,  # oldest -> newest
    }
    while True:
        page = table.query(**kwargs)
        items.extend(page.get("Items", []))
        lek = page.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    shots = [
        {
            "ts": it["gsi1sk"],
            "club": it["club"],
            "distance_yds": float(it["distance_yds"]),
            "from_lat": float(it["from_lat"]),
            "from_lon": float(it["from_lon"]),
            "to_lat": float(it["to_lat"]),
            "to_lon": float(it["to_lon"]),
            "accuracy": float(it["from_accuracy"]) if "from_accuracy" in it else None,
            "edited": bool(it.get("edited")),
            "user": it.get("userName", "player"),
            "mine": it.get("userId") == sub,
        }
        for it in items
    ]
    return resp(200, {"count": len(shots), "shots": shots})
