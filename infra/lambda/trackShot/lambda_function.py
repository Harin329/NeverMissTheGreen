import json
import math
import os
import time
import boto3

TABLE = os.environ.get("TABLE_NAME", "golf_shots")
API_KEY = os.environ.get("API_KEY", "")
RESET_DISTANCE_YDS = 400
RESET_GAP_SECONDS = 3600
PUTTER_NAMES = {"putter", "p", "putt"}
END_NAMES = {"end"}

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE)


def is_putter(club):
    return str(club).strip().lower() in PUTTER_NAMES


def is_end(club):
    return str(club).strip().lower() in END_NAMES


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
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def write_pending(club, lat, lon, epoch, ts, accuracy):
    item = {
        "pk": "STATE",
        "sk": "PENDING",
        "club": club,
        "lat": str(lat),
        "lon": str(lon),
        "epoch": epoch,
        "ts": ts,
    }
    if accuracy is not None:
        item["accuracy"] = str(accuracy)
    table.put_item(Item=item)


def log_shot(pending, lat, lon, ts, dist):
    shot = {
        "pk": "SHOT",
        "sk": ts,
        "club": pending["club"],
        "distance_yds": str(dist),
        "from_lat": str(pending["lat"]),
        "from_lon": str(pending["lon"]),
        "to_lat": str(lat),
        "to_lon": str(lon),
    }
    if pending.get("accuracy") is not None:
        shot["from_accuracy"] = str(pending["accuracy"])
    table.put_item(Item=shot)


def clear_pending():
    table.delete_item(Key={"pk": "STATE", "sk": "PENDING"})


def lambda_handler(event, context):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"error": "invalid JSON"})

    if API_KEY:
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        if headers.get("x-api-key") != API_KEY:
            return resp(401, {"error": "unauthorized"})

    if body.get("reset"):
        clear_pending()
        return resp(200, {"status": "round reset"})

    try:
        club = str(body["club"])
        lat = float(body["lat"])
        lon = float(body["lon"])
    except (KeyError, ValueError, TypeError):
        return resp(400, {"error": "need club, lat, lon"})

    ts = body.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    accuracy = body.get("accuracy")
    now = int(time.time())

    pending = table.get_item(Key={"pk": "STATE", "sk": "PENDING"}).get("Item")

    # ---- END: terminate the round ----
    if is_end(club):
        if not pending:
            return resp(200, {"status": "round ended (nothing pending)", "logged": False})

        if is_putter(pending["club"]):
            # holed with a putt; pending putter was the at-hole scan. No distance.
            clear_pending()
            return resp(200, {"status": "round ended after putt", "logged": False})

        # holed out with a non-putter; end pressed AT the hole -> log final shot.
        dist = distance_yards(float(pending["lat"]), float(pending["lon"]), lat, lon)
        if dist > RESET_DISTANCE_YDS:
            clear_pending()
            return resp(200, {
                "status": "round ended (final shot skipped, implausible distance)",
                "skipped_distance": dist,
                "logged": False,
            })
        log_shot(pending, lat, lon, ts, dist)
        clear_pending()
        return resp(200, {
            "status": "round ended, final shot logged",
            "club": pending["club"],
            "distance_yds": dist,
            "logged": True,
        })

    # ---- no pending: first shot of the round ----
    if not pending:
        write_pending(club, lat, lon, now, ts, accuracy)
        return resp(200, {"status": "first shot of round", "logged": False})

    prev_is_putter = is_putter(pending["club"])
    curr_is_putter = is_putter(club)

    # ---- putter -> non-putter: holed out, new hole, don't log ----
    if prev_is_putter and not curr_is_putter:
        write_pending(club, lat, lon, now, ts, accuracy)
        return resp(200, {"status": "holed out, new hole", "logged": False})

    # ---- normal shot: log distance for the pending club ----
    dist = distance_yards(float(pending["lat"]), float(pending["lon"]), lat, lon)
    gap = now - int(pending.get("epoch", now))

    if dist > RESET_DISTANCE_YDS or gap > RESET_GAP_SECONDS:
        write_pending(club, lat, lon, now, ts, accuracy)
        return resp(200, {
            "status": "new round (gap detected)",
            "skipped_distance": dist,
            "logged": False,
        })

    log_shot(pending, lat, lon, ts, dist)
    write_pending(club, lat, lon, now, ts, accuracy)
    return resp(200, {
        "status": "shot logged",
        "club": pending["club"],
        "distance_yds": dist,
        "logged": True,
    })