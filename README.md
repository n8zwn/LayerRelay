# LayerRelay (nozzle + timelapse fork)

This is my fork of [LayerRelay](https://github.com/GoByeBye/LayerRelay) by GoByeBye, a
self-hosted monitoring dashboard for Prusa printers with a live camera feed,
telemetry, and an optional OBS overlay. Everything the original does still works
the same way, and the full docs live upstream. This README only covers what I
changed.

I run a Prusa CORE One with a toolchanger and wanted a nozzle camera next to the
chamber view, plus automatic timelapses, so I added both.

## What's different here

**A second (nozzle) camera with a floating overlay.** Upstream handles one
camera. I added an optional second one that shows up as a small picture-in-picture
window on the dashboard. You can grab its title bar and drag it anywhere, resize
it from the corner, and it remembers where you left it. That last part matters
for OBS browser sources, which reload on scene change. Add `?nozzle=0` or
`?nozzle=1` to force it hidden or shown for a given source.

**Direct, low-latency nozzle stream.** The PiP can load a stream straight from
the browser instead of going through a server-side relay. I point mine at
[go2rtc](https://github.com/AlexxIT/go2rtc) running on the Pi the camera is
plugged into. Going direct dropped the lag from minutes to real time, since the
frames aren't being re-buffered on the way through. If you'd rather keep it
same-origin, there's still a server-side relay option. When you use a direct URL
the app adds that origin to its Content-Security-Policy so the browser will load
it.

**A timelapse link in the dashboard.** A `Timelapses` entry in the dashboard
controls that opens the gallery from the companion service below. It only shows
up if you set the URL.

**A timelapse companion service.** A small separate container (in `timelapse/`)
that watches the printer state, pulls frames from both cameras while a print is
running, and renders an MP4 per camera when the print finishes. It also serves a
page to browse and download the results. It only reads LayerRelay's public
snapshot endpoints, so it doesn't change how LayerRelay itself behaves.

## New config options

Add these to your `config.json` next to the existing settings. Full list with
defaults is in `config.example.json` and `docs/configuration.md`.

| Key | What it does |
|---|---|
| `nozzlePipUrl` | Browser-facing stream URL for the nozzle PiP, e.g. `http://<pi>:1984/api/stream.mjpeg?src=nozzle`. This is the low-latency path and what I use. |
| `nozzleRtspUrl` | RTSP source if you'd rather have LayerRelay relay the nozzle itself (served at `/api/nozzle.mjpeg`). Leave it out if you're using `nozzlePipUrl`. |
| `nozzleStreamEnabled`, `nozzleStreamFps`, `nozzleStreamWidth`, `nozzleStreamJpegQuality` | Tuning for that server-side relay. Only relevant if you set `nozzleRtspUrl`. |
| `timelapseUrl` | URL of the timelapse gallery, shown as a link in the dashboard controls. |

## Running it

Build and run it the same way as upstream (see their [Docker guide](https://github.com/GoByeBye/LayerRelay/blob/master/docs/docker.md)),
just build from this repo (`github.com/n8zwn/LayerRelay`, branch `nozzle-camera`)
instead of the original. The only thing to add is the config keys above.

For the nozzle you'll want a camera exposed as a browser-reachable stream. Get a
real **UVC** camera so it shows up as `/dev/video0` on Linux with no drivers.
Skip anything sold as an "endoscope" that needs a phone app — a lot of those use
a proprietary protocol and won't work on Linux at all. The one I use and can
confirm works is [this Teslong USB camera](https://a.co/d/08pWZIT9). Plug it into
a Raspberry Pi and turn it into a stream with go2rtc:

```yaml
# go2rtc.yaml on the Pi
streams:
  nozzle:
    - ffmpeg:device?video=0&input_format=mjpeg&video_size=1280x720&framerate=25#video=mjpeg
```

Then set `nozzlePipUrl` to `http://<pi-ip>:1984/api/stream.mjpeg?src=nozzle`. The
device viewing the dashboard needs to be able to reach that address.

## Timelapse companion

The `timelapse/` folder is self-contained with its own `Dockerfile`,
`docker-compose.yml`, and README. Quick version:

```sh
cd timelapse
# edit the compose env: point LAYERRELAY_URL at your LayerRelay,
# NOZZLE_SNAPSHOT_URL at go2rtc, and pick an output folder
docker compose -f timelapse-compose.yml up -d --build
```

It captures during prints, renders `<print name>_<date>_<camera>.mp4` for each
camera when a print finishes, and serves them at `http://<host>:8088/`. Point
`timelapseUrl` at that address to get the dashboard link. See
`timelapse/README.md` for the rest.

## Security and exposure

None of this is authenticated. The dashboard, the nozzle stream (go2rtc), and the
timelapse gallery all serve to anyone who can reach their ports, and those feeds
show your printer and whatever's around it. Keep everything on a trusted local
network behind a firewall.

Putting any of this on the public internet is at your own risk. If you want
remote access, use a VPN (WireGuard, Tailscale) or an authenticated reverse proxy
with TLS instead of forwarding the ports. I don't take responsibility for what
happens if you expose it directly.

## License and credit

LayerRelay was written by GoByeBye and is licensed
[AGPL-3.0-or-later](LICENSE). This is a modified version; the original is at
<https://github.com/GoByeBye/LayerRelay>. Under the AGPL, if you run a modified
copy that other people can reach over a network, you need to publish your source
and point the dashboard's source link at it. Set `sourceCodeUrl` in your config
(or the `SOURCE_CODE_URL` build arg / env) to <https://github.com/n8zwn/LayerRelay>.
