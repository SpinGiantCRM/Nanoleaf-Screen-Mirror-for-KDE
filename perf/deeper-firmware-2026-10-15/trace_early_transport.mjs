// Selected pinned Desktop 2.1.0 class only. Fake HID; never launch the vendor app.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

const [path, ...extra] = process.argv.slice(2);
if (!path || extra.length) throw new Error('Usage: node trace_early_transport.mjs PRIVATE_2_1_0_SERVER_JS');
const stat = fs.statSync(path);
if (!stat.isFile() || stat.size > 8 * 1024 * 1024) throw new Error('Expected bounded regular source file');
const bytes = fs.readFileSync(path);
const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');
if (sha256 !== 'a1606cd70ce0e9a9cd901766cfd2cb079c912eabae937ac561919893ba10ed26') throw new Error('Unexpected Desktop 2.1.0 source hash');
// UTF-16 offsets from the Acorn 8.19.0 class index, not byte offsets.
const snippet = bytes.toString('utf8').slice(2270270, 2275171);
assert(snippet.startsWith('class e{'));
class Queue {
  tail = Promise.resolve();
  add(work) {
    const result = this.tail.then(work);
    this.tail = result.catch(() => {});
    return result;
  }
}
const context = vm.createContext({
  Hf: Queue,
  hn: {chunk: (a, n) => Array.from({length: Math.ceil(a.length / n)}, (_, i) => a.slice(i * n, (i + 1) * n))},
  setTimeout: () => 0,
}, {codeGeneration: {strings: false, wasm: false}});
const Driver = new vm.Script(`(${snippet})`).runInContext(context, {timeout: 100});
const cases = [];
for (const rgb of [[0, 0, 0], [3, 5, 7], [255, 255, 255]]) {
  const reports = [];
  let reads = 0;
  const fake = {
    write: async report => {reports.push(Array.from(report)); return report.length;},
    read: async () => {reads++; throw new Error('No ACK supplied by this fake HID');},
  };
  const driver = new Driver(fake, {productId: 33282}, 48);
  const colors = new Map(Array.from({length: 48}, (_, i) => [i, {r: rgb[0], g: rgb[1], b: rgb[2]}]));
  await driver.setLedColours(colors);
  assert.equal(reads, 0);
  assert.deepEqual(reports.map(r => r.length), [65, 65, 20]);
  assert(reports.every(r => r[0] === 0));
  const packet = reports.flatMap(r => r.slice(1));
  const grb = [rgb[1], rgb[0], rgb[2]].map(c => Math.trunc(c / 2));
  assert.deepEqual(packet, [2, 0, 144, ...Array.from({length: 48}, () => grb).flat()]);
  cases.push({input_rgb: rgb, wire_grb: grb, report_sizes: reports.map(r => r.length), read_calls: reads, completed_without_ack: true});
}
console.log(JSON.stringify({
  scope: 'Selected pinned historical class with fake HID and a substitute serial write queue; no hardware, app startup or optical timing',
  source_sha256: sha256,
  class_utf16_range: [2270270, 2275171],
  cases,
  recommendation: 'Historical write-only behaviour does not establish current firmware safety; keep daily acknowledged transactions',
}, null, 2));
