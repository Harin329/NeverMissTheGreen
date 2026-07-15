import hashlib
import json
import math
import os
import time

import boto3

TABLE = os.environ.get("TABLE_NAME", "golf_shots")
# transition flag: when "1", POSTs without a device key fall back to the
# original single-user keying so pre-auth Shortcuts keep working
ALLOW_LEGACY_TRACK = os.environ.get("ALLOW_LEGACY_TRACK", "")
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


def resolve_user(event):
    """Map the x-api-key device key to a user; None means unauthorized."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    key = headers.get("x-api-key")
    if key:
        h = hashlib.sha256(key.encode()).hexdigest()
        rec = table.get_item(Key={"pk": f"KEY#{h}", "sk": "KEY"}).get("Item")
        if not rec:
            return None
        return {"id": rec["userId"], "name": rec.get("userName", "player")}
    if ALLOW_LEGACY_TRACK == "1":
        return {"legacy": True}
    return None


class Store:
    """Key layout for one user's rows (or the legacy single-user layout)."""

    def __init__(self, user):
        self.legacy = user.get("legacy", False)
        self.user_id = user.get("id")
        self.user_name = user.get("name")

    def pending_key(self):
        if self.legacy:
            return {"pk": "STATE", "sk": "PENDING"}
        return {"pk": f"USER#{self.user_id}", "sk": "STATE#PENDING"}

    def shot_item(self, ts):
        if self.legacy:
            return {"pk": "SHOT", "sk": ts}
        return {
            "pk": f"USER#{self.user_id}", "sk": f"SHOT#{ts}",
            "gsi1pk": "SHOT", "gsi1sk": ts,
            "userId": self.user_id, "userName": self.user_name,
        }


def write_pending(store, club, lat, lon, epoch, ts, accuracy):
    item = store.pending_key()
    item.update({
        "club": club,
        "lat": str(lat),
        "lon": str(lon),
        "epoch": epoch,
        "ts": ts,
    })
    if accuracy is not None:
        item["accuracy"] = str(accuracy)
    table.put_item(Item=item)


def log_shot(store, pending, lat, lon, ts, dist):
    shot = store.shot_item(ts)
    shot.update({
        "club": pending["club"],
        "distance_yds": str(dist),
        "from_lat": str(pending["lat"]),
        "from_lon": str(pending["lon"]),
        "to_lat": str(lat),
        "to_lon": str(lon),
    })
    if pending.get("accuracy") is not None:
        shot["from_accuracy"] = str(pending["accuracy"])
    table.put_item(Item=shot)


def clear_pending(store):
    table.delete_item(Key=store.pending_key())


def lambda_handler(event, context):
    user = resolve_user(event)
    if user is None:
        return resp(401, {"error": "unauthorized"})
    store = Store(user)

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return resp(400, {"error": "invalid JSON"})

    if body.get("reset"):
        clear_pending(store)
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

    pending = table.get_item(Key=store.pending_key()).get("Item")

    # ---- END: terminate the round ----
    if is_end(club):
        if not pending:
            return resp(200, {"status": "round ended (nothing pending)", "logged": False})

        if is_putter(pending["club"]):
            # holed with a putt; pending putter was the at-hole scan. No distance.
            clear_pending(store)
            return resp(200, {"status": "round ended after putt", "logged": False})

        # holed out with a non-putter; end pressed AT the hole -> log final shot.
        dist = distance_yards(float(pending["lat"]), float(pending["lon"]), lat, lon)
        if dist > RESET_DISTANCE_YDS:
            clear_pending(store)
            return resp(200, {
                "status": "round ended (final shot skipped, implausible distance)",
                "skipped_distance": dist,
                "logged": False,
            })
        log_shot(store, pending, lat, lon, ts, dist)
        clear_pending(store)
        return resp(200, {
            "status": "round ended, final shot logged",
            "club": pending["club"],
            "distance_yds": dist,
            "logged": True,
        })

    # ---- no pending: first shot of the round ----
    if not pending:
        write_pending(store, club, lat, lon, now, ts, accuracy)
        return resp(200, {"status": "first shot of round", "logged": False})

    prev_is_putter = is_putter(pending["club"])
    curr_is_putter = is_putter(club)

    # ---- putter -> non-putter: holed out, new hole, don't log ----
    if prev_is_putter and not curr_is_putter:
        write_pending(store, club, lat, lon, now, ts, accuracy)
        return resp(200, {"status": "holed out, new hole", "logged": False})

    # ---- normal shot: log distance for the pending club ----
    dist = distance_yards(float(pending["lat"]), float(pending["lon"]), lat, lon)
    gap = now - int(pending.get("epoch", now))

    if dist > RESET_DISTANCE_YDS or gap > RESET_GAP_SECONDS:
        write_pending(store, club, lat, lon, now, ts, accuracy)
        return resp(200, {
            "status": "new round (gap detected)",
            "skipped_distance": dist,
            "logged": False,
        })

    log_shot(store, pending, lat, lon, ts, dist)
    write_pending(store, club, lat, lon, now, ts, accuracy)
    return resp(200, {
        "status": "shot logged",
        "club": pending["club"],
        "distance_yds": dist,
        "logged": True,
    })
