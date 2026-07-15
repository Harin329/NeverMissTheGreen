import json
import os
import boto3
from boto3.dynamodb.conditions import Key

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


def lambda_handler(event, context):
    if API_KEY:
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        # allow key via header OR ?key= query param (easier from a browser)
        qs = event.get("queryStringParameters") or {}
        supplied = headers.get("x-api-key") or qs.get("key")
        if supplied != API_KEY:
            return resp(401, {"error": "unauthorized"})

    items = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq("SHOT"),
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
            "ts": it["sk"],
            "club": it["club"],
            "distance_yds": float(it["distance_yds"]),
            "from_lat": float(it["from_lat"]),
            "from_lon": float(it["from_lon"]),
            "to_lat": float(it["to_lat"]),
            "to_lon": float(it["to_lon"]),
            "accuracy": float(it["from_accuracy"]) if "from_accuracy" in it else None,
        }
        for it in items
    ]
    return resp(200, {"count": len(shots), "shots": shots})