#!/usr/bin/env python3
"""
Print-aware timelapse for LayerRelay cameras.

Watches LayerRelay's /api/state. While a print is active it grabs a JPEG
snapshot from each configured camera every INTERVAL_SEC. When the print ends
(or a new job starts), it renders one MP4 per camera with ffmpeg into OUTPUT_DIR.

Nothing is written to LayerRelay; this only reads its public snapshot endpoints,
so it stays within LayerRelay's read-only design.

Key env vars (all optional except LAYERRELAY_URL in practice):
  LAYERRELAY_URL        e.g. http://192.168.1.50:8787   (reachable from this container)
  CAPTURE_CHAMBER       true/false          (default true)
  CAPTURE_NOZZLE        true/false          (default true)
  CHAMBER_SNAPSHOT_URL  default {LAYERRELAY_URL}/api/camera.jpg
  NOZZLE_SNAPSHOT_URL   default {LAYERRELAY_URL}/api/nozzle.jpg
                        (or point at go2rtc: http://<pi>:1984/api/frame.jpeg?src=nozzle)
  INTERVAL_SEC          seconds between frames while printing (default 10)
  OUTPUT_FPS            playback fps of the rendered video (default 30)
  OUTPUT_DIR            where finished MP4s go (default /timelapses)
  FRAMES_DIR            scratch frame storage (default /frames)
  KEEP_FRAMES           keep raw frames after rendering (default false)
  MIN_FRAMES            don't render segments shorter than this (default 8)
  STATE_FIELD           dotted path to the printer state string (default state)
  PRINTING_REGEX        regex marking an active print (default (?i)print)
  PROGRESS_FIELD        dotted path to progress, used as a fallback (default progress)
  JOB_ID_FIELDS         comma list of fields to identify a job (default jobKey,thumbnailKey,name)
  DEBUG                 log detection each poll (default true)
"""
import os
import re
import sys
import json
import time
import html
import signal
import shutil
import threading
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


def env(name, default=None):
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def env_bool(name, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


LAYERRELAY_URL = env("LAYERRELAY_URL", "http://localhost:8787").rstrip("/")
INTERVAL = float(env("INTERVAL_SEC", "10"))
FPS = int(env("OUTPUT_FPS", "30"))
OUTPUT_DIR = env("OUTPUT_DIR", "/timelapses")
FRAMES_DIR = env("FRAMES_DIR", "/frames")
KEEP_FRAMES = env_bool("KEEP_FRAMES", False)
MIN_FRAMES = int(env("MIN_FRAMES", "8"))
STATE_FIELD = env("STATE_FIELD", "state")
PRINTING_REGEX = re.compile(env("PRINTING_REGEX", "(?i)print"))
PROGRESS_FIELD = env("PROGRESS_FIELD", "progress")
JOB_ID_FIELDS = [f.strip() for f in env("JOB_ID_FIELDS", "jobKey,thumbnailKey,name").split(",") if f.strip()]
NAME_FIELD = env("NAME_FIELD", "name")   # friendly print name, used in the filename
WEB_PORT = int(env("WEB_PORT", "8088"))  # browse/download gallery port (0 to disable)
ALLOW_DELETE = env_bool("ALLOW_DELETE", True)  # allow deleting timelapses from the page
DEBUG = env_bool("DEBUG", True)
INTERVAL_FIELD = env("TIMELAPSE_INTERVAL_FIELD", "timelapseIntervalSec")  # from /api/state

CAMERAS = {}
if env_bool("CAPTURE_CHAMBER", True):
    CAMERAS["chamber"] = env("CHAMBER_SNAPSHOT_URL", LAYERRELAY_URL + "/api/camera.jpg")
if env_bool("CAPTURE_NOZZLE", True):
    CAMERAS["nozzle"] = env("NOZZLE_SNAPSHOT_URL", LAYERRELAY_URL + "/api/nozzle.jpg")


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), "timelapse:", *a, flush=True)


def dotted(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def fetch_json(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_bytes(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        if getattr(r, "status", 200) != 200:
            return None
        return r.read()


def grab_frame(url, timeout=12):
    """One JPEG from a camera source. rtsp:// is pulled directly with ffmpeg (its
    own short-lived connection, so it never becomes an MJPEG subscriber on the
    relay); http(s):// is fetched as a snapshot."""
    if url.lower().startswith(("rtsp://", "rtsps://")):
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
               "-rtsp_transport", "tcp", "-i", url,
               "-frames:v", "1", "-q:v", "2", "-f", "mjpeg", "pipe:1"]
        try:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, timeout=timeout)
        except Exception:
            return None
        data = proc.stdout or b""
        return data if data[:2] == b"\xff\xd8" else None
    try:
        return fetch_bytes(url)
    except Exception:
        return None


def detect_printing(state):
    s = dotted(state, STATE_FIELD)
    if isinstance(s, str) and PRINTING_REGEX.search(s):
        return True, s
    # Fallback: a fractional/percent progress that isn't 0 or complete.
    p = dotted(state, PROGRESS_FIELD)
    if isinstance(p, (int, float)):
        frac = p / 100.0 if p > 1 else p
        if 0.0 < frac < 0.999:
            return True, "progress=%.3f" % frac
    return False, (s if isinstance(s, str) else None)


def detect_job_id(state):
    for f in JOB_ID_FIELDS:
        v = dotted(state, f)
        if isinstance(v, str) and v.strip():
            return re.sub(r"[^A-Za-z0-9._-]+", "_", v.strip())[:60]
        if isinstance(v, (int, float)):
            return str(v)
    return None


def sanitize_name(s):
    # Filename-safe: keep letters/digits/dot/dash, collapse the rest to '_'.
    s = re.sub(r"\.(bgcode|gcode)$", "", str(s).strip(), flags=re.I)
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_.")
    return s[:60]


def detect_job_name(state):
    v = dotted(state, NAME_FIELD)
    if isinstance(v, str) and v.strip():
        return sanitize_name(v)
    return None


class Segment:
    def __init__(self, job_id, name=None):
        self.job_id = job_id
        # Friendly print name for the filename; fall back to the job id or "print".
        self.name = name or (self._safe(job_id) if job_id else None) or "print"
        self.name_final = bool(name)   # False until a real print name is seen
        self.stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dirs = {}
        self.counts = {}
        for cam in CAMERAS:
            d = os.path.join(FRAMES_DIR, "%s_%s_%s" % (self.stamp, self._safe(job_id), cam))
            os.makedirs(d, exist_ok=True)
            self.dirs[cam] = d
            self.counts[cam] = 0

    @staticmethod
    def _safe(s):
        return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s))[:40]

    def capture(self):
        for cam, url in CAMERAS.items():
            data = grab_frame(url)
            if not data or len(data) < 100:
                if DEBUG:
                    log("no frame from %s" % cam)
                continue
            n = self.counts[cam]
            with open(os.path.join(self.dirs[cam], "f_%06d.jpg" % n), "wb") as fh:
                fh.write(data)
            self.counts[cam] = n + 1

    def render(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        made = []
        for cam, d in self.dirs.items():
            n = self.counts[cam]
            if n < MIN_FRAMES:
                log("skip %s: only %d frame(s)" % (cam, n))
                continue
            # Filename: <print name>_<date-time>_<camera>.mp4
            out = os.path.join(OUTPUT_DIR, "%s_%s_%s.mp4" % (self.name, self.stamp, cam))
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", str(FPS),
                "-i", os.path.join(d, "f_%06d.jpg"),
                # even dimensions required by yuv420p/H.264
                "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                out,
            ]
            try:
                subprocess.run(cmd, check=True)
                log("rendered %s (%d frames) -> %s" % (cam, n, out))
                made.append(out)
            except Exception as e:
                log("render %s failed: %s" % (cam, e))
        if not KEEP_FRAMES:
            for d in self.dirs.values():
                shutil.rmtree(d, ignore_errors=True)
        return made


segment = None


def finish_segment():
    global segment
    if segment is not None:
        total = sum(segment.counts.values())
        log("print ended; rendering segment (%d frames total)" % total)
        segment.render()
        segment = None


def handle_signal(signum, frame):
    log("signal %d received; finishing current segment" % signum)
    finish_segment()
    sys.exit(0)


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024


def list_videos():
    try:
        files = [f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".mp4")]
    except FileNotFoundError:
        return []
    files.sort(key=lambda f: os.path.getmtime(os.path.join(OUTPUT_DIR, f)), reverse=True)
    return files


PAGE_HEAD = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Timelapses</title>
<style>
  :root{--bg:#0f1115;--card:#171a21;--border:#2a2f3a;--text:#e6e9ef;--muted:#9aa3b2;--accent:#ff8a3d}
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);
    font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  h1{padding:18px 20px;margin:0;font-size:20px;border-bottom:1px solid var(--border)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;padding:20px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
  .card video{width:100%;background:#000;display:block;aspect-ratio:16/9;object-fit:contain}
  .meta{padding:10px 12px 6px}
  .title{display:block;font-size:13px;word-break:break-all}
  .sub{display:block;color:var(--muted);font-size:12px;margin-top:2px}
  .foot{display:flex;border-top:1px solid var(--border)}
  .dl,.del{flex:1;text-align:center;padding:9px;font-size:13px;color:var(--text);
    text-decoration:none;background:none;border:0;cursor:pointer;font-family:inherit}
  .del{border-left:1px solid var(--border);color:#e08a8a}
  .dl:hover{color:var(--accent)} .del:hover{color:#ff6b6b}
  .empty{color:var(--muted);padding:24px 20px}
</style></head><body>"""


DELETE_SCRIPT = (
    "<script>\n"
    "document.addEventListener('click', function (e) {\n"
    "  var b = e.target.closest('.del'); if (!b) return;\n"
    "  var name = b.getAttribute('data-file');\n"
    "  if (!confirm('Delete ' + name + '?')) return;\n"
    "  fetch('/' + encodeURIComponent(name), { method: 'DELETE' }).then(function (r) {\n"
    "    if (r.ok) { var c = b.closest('.card'); if (c) c.remove(); }\n"
    "    else alert('Delete failed (' + r.status + ')');\n"
    "  }).catch(function () { alert('Delete failed'); });\n"
    "});\n"
    "</script>"
)


class GalleryHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._gallery()
        return self._serve_file(path)

    @staticmethod
    def _resolve_mp4(path):
        # Map a request path to a .mp4 inside OUTPUT_DIR, or None. Blocks traversal.
        name = urllib.parse.unquote(path.lstrip("/"))
        if "/" in name or ".." in name or "\x00" in name or not name.lower().endswith(".mp4"):
            return None
        return os.path.join(OUTPUT_DIR, name)

    def _serve_file(self, path):
        full = self._resolve_mp4(path)
        if not full or not os.path.isfile(full):
            self.send_error(404); return
        size = os.path.getsize(full)
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                s, e = m.group(1), m.group(2)
                if s == "" and e != "":
                    start, end = max(0, size - int(e)), size - 1
                else:
                    start = int(s) if s else 0
                    end = int(e) if e else size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.end_headers(); return
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(full, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def do_DELETE(self):
        if not ALLOW_DELETE:
            self.send_error(403); return
        # CSRF guard: reject cross-origin requests (browsers send Origin on DELETE).
        origin = self.headers.get("Origin")
        if origin:
            try:
                if urllib.parse.urlparse(origin).netloc != (self.headers.get("Host") or ""):
                    self.send_error(403); return
            except Exception:
                self.send_error(403); return
        full = self._resolve_mp4(self.path.split("?", 1)[0])
        if not full or not os.path.isfile(full):
            self.send_error(404); return
        try:
            os.remove(full)
        except OSError:
            self.send_error(500); return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _gallery(self):
        items = []
        for f in list_videos():
            full = os.path.join(OUTPUT_DIR, f)
            try:
                size = human_size(os.path.getsize(full))
                mt = datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d %H:%M")
            except OSError:
                continue
            url = "/" + urllib.parse.quote(f)
            fesc = html.escape(f)
            del_btn = ('<button class="del" data-file="%s">Delete</button>' % fesc) if ALLOW_DELETE else ""
            items.append(
                '<div class="card"><video controls preload="none" src="%s"></video>'
                '<div class="meta"><span class="title">%s</span>'
                '<span class="sub">%s &middot; %s</span></div>'
                '<div class="foot"><a class="dl" href="%s" download>Download</a>%s</div></div>'
                % (url, fesc, mt, size, url, del_btn)
            )
        if not items:
            items.append('<p class="empty">No timelapses yet &mdash; they appear here after a print finishes.</p>')
        tail = (DELETE_SCRIPT if ALLOW_DELETE else "") + "</body></html>"
        data = (PAGE_HEAD + "<h1>Timelapses</h1><div class=\"grid\">"
                + "".join(items) + "</div>" + tail).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def start_web():
    if WEB_PORT <= 0:
        return
    srv = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), GalleryHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log("gallery at http://0.0.0.0:%d/" % WEB_PORT)


def main():
    start_web()
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    os.makedirs(FRAMES_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    log("watching %s; cameras=%s; interval=%ss; fps=%s; out=%s"
        % (LAYERRELAY_URL, list(CAMERAS), INTERVAL, FPS, OUTPUT_DIR))
    if not CAMERAS:
        log("no cameras enabled; set CAPTURE_CHAMBER/CAPTURE_NOZZLE"); return

    global segment
    while True:
        try:
            state = fetch_json(LAYERRELAY_URL + "/api/state")
        except Exception as e:
            log("state fetch failed: %s (retrying)" % e)
            time.sleep(min(INTERVAL, 5))
            continue

        # Interval can be set live from the LayerRelay overlay slider (1-20s);
        # fall back to INTERVAL_SEC when the field isn't present.
        eff_interval = INTERVAL
        iv = dotted(state, INTERVAL_FIELD)
        if isinstance(iv, (int, float)) and 1 <= iv <= 20:
            eff_interval = float(iv)
        printing, detail = detect_printing(state)
        job_id = detect_job_id(state) or "job"
        job_name = detect_job_name(state)

        if DEBUG:
            log("state=%r printing=%s job=%s frames=%s"
                % (detail, printing, job_id, (segment.counts if segment else {})))

        if printing:
            if segment is None:
                log("print started (job=%s); capturing" % job_id)
                segment = Segment(job_id, job_name)
            elif segment.job_id != job_id and job_id != "job":
                log("new job detected; rendering previous then starting new")
                finish_segment()
                segment = Segment(job_id, job_name)
            # Adopt the friendly print name if it only appeared after the print began.
            if job_name and not segment.name_final:
                segment.name = job_name
                segment.name_final = True
            segment.capture()
        else:
            if segment is not None:
                finish_segment()

        time.sleep(eff_interval)


if __name__ == "__main__":
    main()
