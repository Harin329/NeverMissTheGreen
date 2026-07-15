# NeverMissTheGreen

Single-page app: the whole site is `index.html` at the repo root (Netlify
deploys that one file as-is; no build step, so keep all site JS/CSS inline).
Backend is Python Lambdas in `infra/lambda/` behind API Gateway, deployed by
CDK from `infra/`. Shots are logged by an iOS Shortcut POSTing club + GPS
scans to `trackShot`; hole/round semantics live in that Lambda.

## PR conventions

Every PR that touches UI must include a screenshot, and ideally a short demo
GIF, of the change running:

1. Drive `index.html` headlessly with the stubbed-auth recipe in
   `.claude/skills/verify/SKILL.md` (Playwright + fixture shots).
2. Record with Playwright `recordVideo`, convert to GIF with an ffmpeg from
   `@ffmpeg-installer/ffmpeg` (keep GIFs under ~2 MB: fps 6–8, ~440px wide).
3. Commit the media to the PR branch under `docs/`, then embed it in the PR
   body with commit-SHA-pinned `raw.githubusercontent.com` URLs (branch-named
   URLs break when the branch is deleted after merge).
