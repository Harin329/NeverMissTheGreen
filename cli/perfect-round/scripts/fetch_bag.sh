#!/usr/bin/env bash
# Regenerate data/bag.json from the NeverMissTheGreen shot log in DynamoDB.
# Requires AWS credentials with read access to the golf_shots table.
set -euo pipefail

USER_SUB="549894d8-f0a1-70ef-6d09-3c1d81480c76"
TABLE="golf_shots"
REGION="us-east-1"
OUT="$(dirname "$0")/../data/bag.json"

SHOTS="$(mktemp)"
trap 'rm -f "$SHOTS"' EXIT

aws dynamodb query --region "$REGION" --table-name "$TABLE" \
  --key-condition-expression "pk = :p AND begins_with(sk, :s)" \
  --expression-attribute-values "{\":p\":{\"S\":\"USER#${USER_SUB}\"},\":s\":{\"S\":\"SHOT#\"}}" \
  --projection-expression "club, distance_yds" \
  --output json > "$SHOTS"

python3 - "$OUT" "$SHOTS" <<'PY'
import json, statistics, collections, sys, datetime, os

# Lateral spread isn't in the shot log (no target line), so it's
# hand-maintained in bag.json — carry existing values across refreshes.
lateral = {}
if os.path.exists(sys.argv[1]):
    try:
        with open(sys.argv[1]) as f:
            for c in json.load(f)["clubs"]:
                lateral[c["club"]] = c.get("lateral_std_dev_yds", 0)
    except (ValueError, KeyError):
        pass

with open(sys.argv[2]) as f:
    data = json.load(f)
by = collections.defaultdict(list)
for item in data["Items"]:
    by[item["club"]["S"]].append(float(item["distance_yds"]["S"]))

# Club codes match the shot log and parse into the CLI's Club enum
# (driver, 3w, 3h, 4ir..9ir, pw, 50/54/58). Unknown codes go last so a
# new club in the log still shows up.
order = ["driver", "3w", "3h", "4ir", "5ir", "6ir", "7ir", "8ir", "9ir",
         "pw", "50", "54", "58"]
codes = order + sorted(set(by) - set(order))

bag = []
total = 0
for code in codes:
    ds = by.get(code)
    if not ds:
        continue
    total += len(ds)
    mean = statistics.mean(ds)
    # Raw observed spread; null when one shot can't define one. The CLI
    # blends this with a prior weighted by sample size — no fudging here.
    sd = round(statistics.stdev(ds), 1) if len(ds) >= 2 else None
    bag.append({"club": code, "avg_dist": round(mean, 1),
                "std_dev_yds": sd, "samples": len(ds),
                "lateral_std_dev_yds": lateral.get(code, 0)})

today = datetime.date.today().isoformat()
with open(sys.argv[1], "w") as f:
    json.dump({"source": f"DynamoDB golf_shots, {total} shots as of {today}",
               "clubs": bag}, f, indent=2)
print(f"wrote {len(bag)} clubs from {total} shots to {sys.argv[1]}")
PY
