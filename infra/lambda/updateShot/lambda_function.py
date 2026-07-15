import json
import math
import os

import boto3

TABLE = os.environ.get("TABLE_NAME", "golf_shots")

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE)


def distance_yards(lat1, lon1, lat2, lon2):
    R = 6371000  # meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    x = dlam * math.cos((p1 + p2) / 2)
    y = dphi
    return round(math.sqrt(x * x + y * y) * R * 1.09361, 1)


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

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"error": "invalid JSON"})

    ts = body.get("ts")
    if not ts:
        return resp(400, {"error": "need ts"})

    key = {"pk": f"USER#{sub}", "sk": f"SHOT#{ts}"}
    existing = table.get_item(Key=key).get("Item")
    if not existing:
        return resp(404, {"error": "no shot with that ts", "ts": ts})

    try:
        f_lat = float(body["from_lat"]); f_lon = float(body["from_lon"])
        t_lat = float(body["to_lat"]);   t_lon = float(body["to_lon"])
    except (KeyError, ValueError, TypeError):
        return resp(400, {"error": "need from_lat, from_lon, to_lat, to_lon"})

    dist = distance_yards(f_lat, f_lon, t_lat, t_lon)
    existing.update({
        "from_lat": str(f_lat), "from_lon": str(f_lon),
        "to_lat": str(t_lat), "to_lon": str(t_lon),
        "distance_yds": str(dist),
        "edited": "1",   # human-corrected; viewer drops the GPS-accuracy flag
    })
    table.put_item(Item=existing)
    return resp(200, {"status": "updated", "ts": ts, "distance_yds": dist})
