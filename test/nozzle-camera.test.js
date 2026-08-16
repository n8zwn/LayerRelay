'use strict';

const assert = require('node:assert/strict');
const { test } = require('bun:test');
const { validateConfig, DEFAULT_CONFIG } = require('../config.js');
const { CameraStream } = require('../camera-stream.js');

const base = {
  printerHost: '192.0.2.10',
  username: 'maker',
  password: 'secret',
  sourceCodeUrl: 'https://github.com/GoByeBye/LayerRelay',
  listenHost: '127.0.0.1',
};

test('accepts a valid nozzle camera configuration', () => {
  const cfg = validateConfig({
    ...base,
    nozzleRtspUrl: 'rtsp://192.0.2.20:8554/nozzle',
    nozzleStreamEnabled: true,
    nozzleStreamFps: 15,
    nozzleStreamWidth: 640,
    nozzleStreamJpegQuality: 6,
  });
  assert.equal(cfg.nozzleRtspUrl, 'rtsp://192.0.2.20:8554/nozzle');
});

test('nozzle is absent by default and off when unset', () => {
  assert.equal('nozzleRtspUrl' in DEFAULT_CONFIG, true);
  assert.equal(DEFAULT_CONFIG.nozzleRtspUrl, '');
  const relay = new CameraStream({ cameraRtspUrl: DEFAULT_CONFIG.nozzleRtspUrl });
  assert.equal(relay.enabled, false);
  assert.equal(relay.getStatus().state, 'disabled');
});

test('rejects a non-RTSP nozzle URL', () => {
  assert.throws(
    () => validateConfig({ ...base, nozzleRtspUrl: 'http://192.0.2.20/stream' }),
    /nozzleRtspUrl must use rtsp/,
  );
});

test('rejects out-of-range nozzle tuning', () => {
  assert.throws(() => validateConfig({ ...base, nozzleStreamFps: 99 }), /nozzleStreamFps/);
  assert.throws(() => validateConfig({ ...base, nozzleStreamWidth: 100 }), /nozzleStreamWidth/);
});

test('a nozzle-style config produces an enabled relay via CameraStream', () => {
  const relay = new CameraStream({
    cameraRtspUrl: 'rtsp://192.0.2.20:8554/nozzle',
    cameraStreamWidth: 640,
    cameraStreamFps: 15,
  });
  assert.equal(relay.enabled, true);
  assert.equal(relay.options.width, 640);
});

test('accepts a valid timelapse URL and rejects a non-http one', () => {
  const ok = validateConfig({ ...base, timelapseUrl: 'http://192.0.2.50:8088/' });
  assert.equal(ok.timelapseUrl, 'http://192.0.2.50:8088/');
  assert.throws(() => validateConfig({ ...base, timelapseUrl: 'ftp://example/x' }), /timelapseUrl must use http/);
  // empty string stays allowed (feature off)
  assert.equal(validateConfig({ ...base, timelapseUrl: '' }).timelapseUrl, '');
});

test('accepts a browser-facing nozzlePipUrl and rejects a bad one', () => {
  const ok = validateConfig({ ...base, nozzlePipUrl: 'http://192.0.2.20:1984/api/stream.mjpeg?src=nozzle' });
  assert.equal(ok.nozzlePipUrl, 'http://192.0.2.20:1984/api/stream.mjpeg?src=nozzle');
  assert.equal(validateConfig({ ...base, nozzlePipUrl: '/api/nozzle.mjpeg' }).nozzlePipUrl, '/api/nozzle.mjpeg');
  assert.throws(() => validateConfig({ ...base, nozzlePipUrl: 'rtsp://x/y' }), /nozzlePipUrl/);
});

test('accepts the nozzleEnabled master switch and rejects a non-boolean', () => {
  assert.equal(validateConfig({ ...base, nozzleEnabled: false }).nozzleEnabled, false);
  assert.throws(() => validateConfig({ ...base, nozzleEnabled: 'no' }), /nozzleEnabled must be true or false/);
});
