# LayerRelay — native nozzle (secondary) camera support

This adds an optional second camera to LayerRelay: its own RTSP relay, HTTP
endpoints, and a picture-in-picture view in the overlay. It is fully backward
compatible — with no nozzle config, nothing changes.

Verified against `master` (commit 5986ec4): `bun test` = 162 pass / 0 fail,
`bun run check` = clean. The patch applies cleanly to a fresh `master`.

## What changed

| File | Change |
|---|---|
| `config.js` | New keys `nozzleRtspUrl`, `nozzleStreamEnabled`, `nozzleStreamFps`, `nozzleStreamWidth`, `nozzleStreamJpegQuality` — known keys, defaults, ranges, RTSP validation, and `NOZZLE_RTSP_URL` / `NOZZLE_STREAM_ENABLED` env overrides. |
| `server.js` | A second `CameraStream` (`nozzleStream`) built from a nozzle profile that reuses the primary relay's tuning. New routes `/api/nozzle.mjpeg`, `/api/nozzle.jpg`, `/api/nozzle/status`; `nozzle` added to `/api/state`; startup log line; clean shutdown. |
| `public/overlay.html` | A `#nozzle-pip` picture-in-picture (top-right), shown when the nozzle relay is enabled, with `?nozzle=0/1` override and auto-reconnect. |
| `config.example.json`, `config.schema.json`, `docs/configuration.md` | Document the new keys. |
| `test/nozzle-camera.test.js` | New tests for validation and relay behavior. |

`camera-stream.js` is intentionally **unchanged** — the nozzle relay reuses the
existing, already-tested class, so there's no risk to the primary camera path.

## How it fits your setup

Your nozzle cam is USB, so it isn't RTSP on its own. The Pi's go2rtc turns it
into RTSP (`rtsp://<pi-ip>:8554/nozzle`), and this feature makes LayerRelay
relay *that* into the dashboard. So keep go2rtc running on the Pi — the two
pieces work together:

    USB nozzle cam -> go2rtc on Pi (RTSP) -> LayerRelay nozzle relay -> dashboard PiP

Once this is running, the standalone `printer-monitor.html` page is no longer
needed — the nozzle view is built into LayerRelay itself.

## 1. Create your private fork and apply the change

On GitHub, click **Fork** on `GoByeBye/LayerRelay` (uncheck "copy the master
branch only" if you want history). Then, on your machine:

```sh
git clone https://github.com/<your-username>/LayerRelay.git
cd LayerRelay
git checkout -b nozzle-camera

# apply the change (copy nozzle-camera.patch into this folder first)
git apply nozzle-camera.patch
# ...or just copy the modified files from this bundle over your clone.

git add -A
git commit -m "Add optional secondary (nozzle) camera relay, endpoints, and overlay PiP"
git push -u origin nozzle-camera
```

## 2. Point your Portainer build stack at your fork

In your repobuild stack, change the build context to your fork and branch:

```yaml
    build:
      context: "https://github.com/<your-username>/LayerRelay.git#nozzle-camera"
```

**AGPL:** because this is now a modified deployment, set the source URL to your
fork so the dashboard's "Source" link is correct. In the stack `environment:`:

```yaml
      SOURCE_CODE_URL: "https://github.com/<your-username>/LayerRelay"
```

## 3. Enable the nozzle camera in your config

Add these to your inline `config.json` (the `content:` block in the stack):

```json
"nozzleRtspUrl": "rtsp://<pi-ip>:8554/nozzle",
"nozzleStreamEnabled": true
```

Optional tuning (defaults shown): `"nozzleStreamFps": 15`,
`"nozzleStreamWidth": 640`, `"nozzleStreamJpegQuality": 6`.

Redeploy the stack (delete the `layer-relay:local` image first so it rebuilds
from your fork). Open the dashboard — the nozzle appears as a picture-in-picture
in the top-right. Direct URLs also work: `/api/nozzle.mjpeg`, `/api/nozzle.jpg`,
`/api/nozzle/status`. Add `?nozzle=0` to hide the PiP for a given browser/source,
`?nozzle=1` to force it.

## 4. Later: open the upstream PR

Once you've confirmed it works, open a PR from your `nozzle-camera` branch to
`GoByeBye/LayerRelay`. Suggested description:

> **Add optional secondary (nozzle) camera**
>
> Adds an optional second camera alongside the existing chamber camera: a second
> `CameraStream` instance driven by new `nozzle*` config keys, `/api/nozzle.*`
> endpoints, a `nozzle` block in `/api/state`, and a picture-in-picture view in
> the overlay (with a `?nozzle=0/1` override). Disabled by default and fully
> backward compatible — `camera-stream.js` is unchanged; the nozzle relay reuses
> it. Docs, schema, example config, and tests included. `bun test` and
> `bun run check` pass.
>
> Motivation: pairing a nozzle cam (e.g. a USB cam exposed over RTSP by go2rtc)
> with the existing chamber view in one dashboard.

Check `CONTRIBUTING.md` and `NOTICE.md` first — the project has an AI-assisted
development disclosure policy you should honor in the PR if relevant.

## Notes / limitations

- The nozzle relay uses the same lazy-start, backpressure, idle-stop, and
  reconnect logic as the primary camera (it's the same class).
- The PiP shows in both the full dashboard and the 420px lower-third overlay when
  enabled; existing users are unaffected because it's off unless configured.
- Nozzle stream tuning is a small subset (fps/width/quality); the deeper relay
  timeouts intentionally inherit the primary camera's values to keep the config
  surface small. Easy to expand later if a reviewer prefers per-field control.
