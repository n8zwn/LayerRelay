'use strict';

const assert = require('node:assert/strict');
const { test } = require('bun:test');
const { validateConfig, DEFAULT_CONFIG } = require('../config.js');
const { hexToRgb, buildWledBody } = require('../wled.js');

const base = {
  printerHost: '192.0.2.10',
  username: 'maker',
  password: 'secret',
  sourceCodeUrl: 'https://github.com/n8zwn/LayerRelay',
  listenHost: '127.0.0.1',
};

test('WLED is off by default with sensible colour defaults', () => {
  assert.equal(DEFAULT_CONFIG.wledEnabled, false);
  assert.equal(DEFAULT_CONFIG.wledHost, '');
  assert.equal(DEFAULT_CONFIG.wledErrorColor, '#ff0000');
  assert.equal(DEFAULT_CONFIG.wledSuccessHoldSec, 300);
});

test('accepts a valid WLED configuration', () => {
  const cfg = validateConfig({
    ...base,
    wledEnabled: true,
    wledHost: '192.168.1.60',
    wledBrightness: 200,
    wledTransitionMs: 700,
    wledSuccessHoldSec: 600,
    wledIdleColor: '#101010',
    wledPrintingColor: '#1030ff',
    wledErrorColor: '#ff0000',
    wledSuccessColor: '#00ff00',
    wledPrintingPreset: 5,
  });
  assert.equal(cfg.wledHost, '192.168.1.60');
  assert.equal(cfg.wledPrintingPreset, 5);
});

test('rejects a WLED host that includes a scheme', () => {
  assert.throws(() => validateConfig({ ...base, wledHost: 'http://192.168.1.60' }), /wledHost/);
});

test('rejects a non-hex WLED colour', () => {
  assert.throws(() => validateConfig({ ...base, wledPrintingColor: 'blue' }), /wledPrintingColor must be a six-digit hex/);
});

test('rejects out-of-range WLED brightness and preset', () => {
  assert.throws(() => validateConfig({ ...base, wledBrightness: 999 }), /wledBrightness/);
  assert.throws(() => validateConfig({ ...base, wledErrorPreset: 300 }), /wledErrorPreset/);
});

test('rejects a non-boolean wledEnabled', () => {
  assert.throws(() => validateConfig({ ...base, wledEnabled: 'yes' }), /wledEnabled must be true or false/);
});

test('hexToRgb parses six-digit hex and rejects junk', () => {
  assert.deepEqual(hexToRgb('#1030ff'), [16, 48, 255]);
  assert.deepEqual(hexToRgb('00ff00'), [0, 255, 0]);
  assert.equal(hexToRgb('nope'), null);
});

test('buildWledBody sets a solid colour on the main segment', () => {
  const body = buildWledBody({ colorHex: '#1030ff', brightness: 128, transitionMs: 400 });
  assert.equal(body.on, true);
  assert.equal(body.bri, 128);
  assert.equal(body.tt, 4); // 400ms -> 4 (100ms units)
  assert.deepEqual(body.seg, [{ id: 0, fx: 0, col: [[16, 48, 255]] }]);
  assert.equal(body.ps, undefined);
});

test('buildWledBody activates a preset instead of a colour when set', () => {
  const body = buildWledBody({ colorHex: '#1030ff', brightness: 128, preset: 3, transitionMs: 700 });
  assert.equal(body.ps, 3);
  assert.equal(body.tt, 7);
  assert.equal(body.seg, undefined);
  assert.equal(body.bri, undefined);
});
