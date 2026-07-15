# NeverMissTheGreen

## Strokes gained

The shot log computes tee-to-green strokes gained per shot against a PGA Tour
baseline (Broadie's expected-strokes tables), entirely client-side from the
logged scan points:

- Holes are rebuilt per player by chaining shots that share a scan point
  (one scan writes shot N's end and shot N+1's start); a break in the chain
  starts a new hole.
- The last point of each hole — where the putter scan happened, or where End
  was pressed — stands in for the pin.
- Each shot scores `E(distance before) − E(distance after) − 1`. The hole's
  first shot is priced off the tee table, everything else off the fairway
  table (lies aren't tracked).
- The shot that ends a hole is treated as having found the green and is
  charged a tour-typical first-putt distance for its length. Putts aren't
  distance-tracked, so putter shots get no SG and putting/penalty strokes are
  out of scope.

Average SG per club shows on each club card, overall SG per shot in the
totals, and each shot row and map popup carries its own SG value.
