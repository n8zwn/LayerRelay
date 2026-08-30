'use strict';

// Minimal WLED status-light controller. LayerRelay pushes a colour (or activates a
// preset) per printer state through the WLED JSON API (`POST /json/state`). This is
// the only place LayerRelay writes to WLED; it never reads or stores WLED state, so
// the strip stays outside LayerRelay's read-only printer boundary.
//
// WLED JSON API reference: https://kno.wled.ge/interfaces/json-api/

const http = require('node:http');

const HEX_RE = /^#?([0-9a-f]{6})$/i;

function hexToRgb(hex) {
  const m = HEX_RE.exec(String(hex || '').trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function clampInt(value, min, max, fallback) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

// Accept an optional "host:port"; default to WLED's port 80. IPv6 literals (multiple
// colons) are passed through unchanged since WLED is virtually always reached by IPv4/mDNS.
function splitHostPort(host) {
  const h = String(host || '').trim();
  const m = /^([^:]+):(\d{1,5})$/.exec(h);
  if (m) return { host: m[1], port: Number(m[2]) };
  return { host: h, port: 80 };
}

// Build a WLED /json/state body for one printer state. When `preset` is a positive
// integer the whole preset is activated (it defines its own colour/effect/brightness);
// otherwise a solid colour (fx 0) is set on the main segment with the given brightness.
function buildWledBody({ colorHex, brightness, preset, transitionMs, on = true } = {}) {
  const body = { on: on !== false };
  // WLED "tt" is a one-shot transition expressed in 100ms units (e.g. 400ms -> 4).
  body.tt = clampInt(Math.round(clampInt(transitionMs, 0, 65000, 400) / 100), 0, 255, 4);
  const presetId = clampInt(preset, 0, 250, 0);
  if (presetId > 0) {
    body.ps = presetId;
    return body;
  }
  const rgb = hexToRgb(colorHex);
  body.bri = clampInt(brightness, 0, 255, 128);
  body.seg = [{ id: 0, fx: 0, col: [rgb || [0, 0, 0]] }];
  return body;
}

// POST a body to http://<host>/json/state. Resolves { ok, status?, error? } and never
// rejects, so a missing/asleep controller can never crash the poll loop.
function postWledState(host, body, { timeoutMs = 3000, port } = {}) {
  const target = splitHostPort(host);
  return new Promise((resolve) => {
    let payload;
    try {
      payload = Buffer.from(JSON.stringify(body), 'utf8');
    } catch (error) {
      resolve({ ok: false, error: error.message });
      return;
    }
    let settled = false;
    const done = (result) => { if (!settled) { settled = true; resolve(result); } };
    let req;
    try {
      req = http.request(
        {
          host: target.host,
          port: port || target.port,
          path: '/json/state',
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Content-Length': payload.length,
          },
        },
        (res) => {
          const ok = res.statusCode >= 200 && res.statusCode < 300;
          res.resume(); // drain and discard; we don't read WLED state
          res.on('end', () => done({ ok, status: res.statusCode }));
          res.on('error', (error) => done({ ok: false, error: error.message }));
        },
      );
    } catch (error) {
      done({ ok: false, error: error.message });
      return;
    }
    req.setTimeout(timeoutMs, () => { req.destroy(new Error('WLED request timed out')); });
    req.on('error', (error) => done({ ok: false, error: error.message }));
    req.write(payload);
    req.end();
  });
}

module.exports = { hexToRgb, buildWledBody, postWledState };
