# Perfect Round

Perfect round is a cli tool which will accept as input a golf course. Based on your average distances, it will then provide you with the clubs you should hit on each hole, taking into account how consistent and accurate you are with each of your clubs.

Club distances come from the NeverMissTheGreen shot log (DynamoDB
`golf_shots`), so the bag improves as more shots are logged.

## Run

```bash
cargo run                                  # Coyote Creek, white tees
cargo run -- --tee black                   # other tee sets
cargo run -- path/to/course.json --bag path/to/bag.json
```

## How it picks clubs

For each shot it considers every club in the bag (driver only off the
tee, plus a part-swing wedge inside full-wedge range) and Monte Carlo
samples the club's carry from `Normal(avg_dist, effective spread)`.
Each candidate is scored as `1 + E[baseline(leave)]`, where `baseline`
is a piecewise-linear expected-strokes-to-hole-out curve for a
mid-handicap amateur. The club with the lowest expectation wins — so a
consistent club that leaves a slightly longer putt can beat a longer
club with a wide dispersion.

A club's *effective* spread weighs its observed spread by sample size:
the raw variance is pooled with a distance-scaled prior (worth 8
pseudo-shots), then widened by `(1 + 1/n)` for the uncertainty of the
average itself. Two shots with a 3-yard spread therefore rate as less
reliable than a hundred shots with a 10-yard spread; a club only earns
a tight distribution by proving it over many logged shots. Run with
`--verbose` to see raw vs effective spread per club.

Known limits (proof of concept):

- Lateral spread (`lateral_std_dev_yds`) is hand-maintained in
  `data/bag.json` — the shot log has no target line to measure it from.
  `fetch_bag.sh` preserves your values across refreshes; zeros disable
  the lateral term.
- No hazards, doglegs, or elevation; every hole is a straight corridor.
- The baseline curve is a generic amateur table, not fit to your data.

## Refresh the bag

```bash
./scripts/fetch_bag.sh   # needs AWS creds for the golf_shots table
```

Course files are hand-entered JSON (see `data/coyote-creek.json`,
scorecard from greenskeeper.org).