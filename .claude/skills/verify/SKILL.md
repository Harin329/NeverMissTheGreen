# Verify: drive the Shot Log page locally

The site is the single root `index.html` (no build step; Netlify deploys it
as-is). Verify UI changes by driving it in headless Chromium with the auth
and API stubbed — no AWS access needed.

## Recipe

1. In a scratch dir: `npm i playwright leaflet@1.9.4` (Chromium is
   pre-installed at `/opt/pw-browsers`; launch with
   `executablePath: "/opt/pw-browsers/chromium"`).
2. Serve `index.html` from a tiny Node/Python HTTP server on localhost.
3. Stub the signed-in state before page scripts run — `jwtExp()` only reads
   the `exp` claim:
   ```js
   const jwt = "e30." + Buffer.from(JSON.stringify({ exp: 9999999999 })).toString("base64url") + ".x";
   await page.addInitScript(t => localStorage.setItem("nmg_id", t), jwt);
   ```
4. Intercept the API with `page.route(url => url.href.includes("execute-api.us-east-1.amazonaws.com"), ...)`
   — use a URL **predicate**, not a `**/host/**` glob (the subdomain has no
   `/` before it, so the glob never matches). Answer OPTIONS preflights with
   204 + `Access-Control-Allow-*: *`, and GET `/shot` with a fixture shaped
   like getShot's response (`{count, shots:[{ts, club, distance_yds,
   from_lat/lon, to_lat/lon, accuracy, edited, user, mine}]}`).
5. The cdnjs Leaflet URLs are blocked by the sandbox proxy — route
   `cdnjs.cloudflare.com` to the npm `leaflet/dist` files, and abort
   `arcgisonline.com` tile requests (the page tolerates a missing map).

## Gotchas

- Fixture geometry: consecutive shots of a hole must share **bit-identical**
  coordinates (one scan writes shot N's `to` and shot N+1's `from`) — build
  points once and reuse the array. `1 yd ≈ 180/π/(6371000*1.09361)` degrees
  of latitude.
- After clicking `#reload`, wait for the loading message to clear, not just
  for `.msg` (it matches "Loading shots…" too).
- Full-page screenshots band/wash out below the fold because of
  `background-attachment: fixed` — screenshot artifact, not a page bug.

Worked flows: totals strip, per-club cards, shot rows, user filter chips,
map popups (click a polyline midpoint via `mapRef.latLngToContainerPoint`),
empty state via reload with an empty fixture.
