// Run with node tests/phone_alarm.cjs; uses the actual inline phone script.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
let started = 0, stopped = 0, socket, responseOk = false;
const context = {
  document: { getElementById: id => {
    if (!elements.has(id)) elements.set(id, { style: {}, textContent: '' });
    return elements.get(id);
  } },
  window: { AudioContext: class {
    currentTime = 0;
    async resume() {}
    createOscillator() {
      return { frequency: {}, connect() {}, start() { started++; }, stop() { stopped++; } };
    }
    createGain() { return { gain: {}, connect() {} }; }
  } },
  navigator: {}, location: { protocol: 'http:', host: 'localhost:8000' },
  WebSocket: class { constructor() { socket = this; } },
  setInterval: () => 1, clearInterval() {}, setTimeout() {},
  fetch: async () => ({ ok: responseOk }),
};
const script = fs.readFileSync('backend/static/phone.html', 'utf8').split('<script>')[1].split('</script>')[0];
vm.runInNewContext(script, context);
const message = value => socket.onmessage({ data: JSON.stringify(value) });
const alert = { type: 'alert', alert_id: 1, seat_id: 'A', source: 'fake', pattern: 'breathing_pause', max_gap_s: 12 };
(async () => {
  message({ type: 'snapshot', alerts: [alert] });
  assert.equal(started, 0);
  await elements.get('arm').onclick();
  assert.equal(started, 1, 'arming after an alert starts the alarm');
  assert.match(elements.get('title').textContent, /DEMO/);
  await elements.get('ack').onclick();
  assert.equal(stopped, 0, 'failed acknowledgement keeps ringing');
  responseOk = true;
  await elements.get('ack').onclick();
  assert.equal(stopped, 1);
  message({ type: 'snapshot', alerts: [alert] });
  assert.equal(started, 2, 'reconnect restores outstanding alarm');
  message({ type: 'ack', alert_id: 1 });
  assert.equal(stopped, 2, 'another phone can acknowledge');
  message({ type: 'snapshot', alerts: [] });
  assert.equal(elements.get('alert').style.display, 'none');
  console.log('Phone alarm checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
