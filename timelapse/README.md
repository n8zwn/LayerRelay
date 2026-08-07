# LayerRelay timelapse service

Print-aware timelapse for both cameras. It watches LayerRelay's `/api/state`,
grabs a JPEG from each camera every few seconds **while a print is running**, and
auto-renders one MP4 per camera when the print finishes. Read-only — it only
pulls LayerRelay's public snapshot endpoints, nothing else.

Files: `timelapse.py`, `Dockerfile`, `timelapse-compose.yml`.

## Setup (on the LayerRelay / Portainer host)

1. Make a folder for the finished videos and give it to the container's
   non-root user (UID 10001), since the container drops root:

   ```sh
   sudo mkdir -p /opt/layerrelay/timelapses
   sudo chown -R 10001:10001 /opt/layerrelay/timelapses
   ```

   (Change the left side of the `/timelapses` bind mount if you want them
   elsewhere — just `chown` that folder too.) If you're upgrading from an
   earlier version that ran as root, drop the old scratch volume so it's
   recreated with the right ownership:

   ```sh
   docker volume rm timelapse_timelapse-frames   # name may vary; `docker volume ls`
   ```

2. Confirm `LAYERRELAY_URL` in the compose. `http://host.docker.internal:8787`
   works when LayerRelay runs on this same host (the `extra_hosts` line makes
   that name resolve on Linux). Otherwise set it to LayerRelay's LAN address.

3. Deploy:

   ```sh
   docker compose -f timelapse-compose.yml up -d --build
   docker logs -f layerrelay-timelapse
   ```

## What you'll see

Each poll logs a line like:

```
timelapse: state='PRINTING' printing=True job=benchy.bgcode frames={'chamber': 42, 'nozzle': 42}
```

- **`printing=False` during an actual print** → detection is off for your
  firmware. Copy your `/api/state` (`curl http://<host>:8787/api/state`) and set
  `STATE_FIELD` / `PRINTING_REGEX` / `JOB_ID_FIELDS` to match — send it to Claude
  and I'll give you the exact values.
- On print end you'll see `rendered chamber (N frames) -> /timelapses/....mp4`
  and the same for the nozzle. Videos are named
  `<print name>_<date-time>_<camera>.mp4`, e.g.
  `Benchy_Boat_v2_20260803-192712_chamber.mp4`. The print name comes from
  LayerRelay's `name` field (override the source with `NAME_FIELD` if needed);
  it falls back to the job id, then `print`, if no name is available.

## Tuning

| Env | Meaning | Default |
|---|---|---|
| `INTERVAL_SEC` | fallback seconds between frames — the LayerRelay overlay's interval slider (1–20s) overrides this live via `/api/state` | 10 |
| `OUTPUT_FPS` | playback speed of the video | 30 |
| `CAPTURE_CHAMBER` / `CAPTURE_NOZZLE` | which cameras | both on |
| `CHAMBER_SNAPSHOT_URL` / `NOZZLE_SNAPSHOT_URL` | camera source per cam. An `rtsp://…` URL is pulled directly with ffmpeg (one connection per frame, no MJPEG subscriber); `http(s)://…` snapshot URLs also work | LayerRelay `/api/camera.jpg` / `/api/nozzle.jpg` |
| `ALLOW_DELETE` | show a Delete button on each card and allow deleting from the page | true |
| `KEEP_FRAMES` | keep raw JPEGs after rendering | false |
| `MIN_FRAMES` | skip rendering very short segments | 8 |

Rule of thumb: video length ≈ (print_minutes × 60 ÷ `INTERVAL_SEC`) ÷ `OUTPUT_FPS`
seconds. A 3-hour print at 10s interval, 30fps ≈ 36s clip. Longer interval =
shorter, choppier clip; shorter interval = smoother but bigger.

## Notes

- Stopping the container mid-print renders what's captured so far (it catches
  `SIGTERM`), so you won't lose a partial timelapse.
- Nozzle timelapses need either the nozzle fork (`/api/nozzle.jpg`) or a
  `NOZZLE_SNAPSHOT_URL` pointing at go2rtc. If neither is reachable, nozzle
  frames are just skipped and you still get the chamber timelapse.
- This is a time-based timelapse. A true "printhead disappears" OctoLapse effect
  needs the printer to park the head each layer, which LayerRelay can't do (it's
  read-only by design).

## Security

The container is hardened: it runs as a non-root user, drops all Linux
capabilities, uses a read-only root filesystem, and sets `no-new-privileges`. It
only reads LayerRelay's public snapshot endpoints and writes the frames/videos.

The gallery on port 8088 has **no authentication** — anyone who can reach the
host can browse and download your timelapses. Keep it on a trusted local network
behind a firewall. Exposing it (or LayerRelay, or go2rtc) to the public internet
is at your own risk; use a VPN or an authenticated reverse proxy with TLS if you
need remote access.
