import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
const [assetPath, parserPath] = process.argv.slice(2);
if(!assetPath || !parserPath) throw new Error('Usage: node trace_vendor_transport.mjs ASSET_JS ACORN_MJS');
if(!fs.statSync(assetPath).isFile() || fs.statSync(assetPath).size>16*1024*1024) throw new Error('Expected bounded regular source file');
const asset=fs.readFileSync(assetPath,'utf8');
if(crypto.createHash('sha256').update(asset).digest('hex')!=='b144b27875322a9e7e0382c7de78674dc76f0f5b3d8a995c0341bc7bc6f3f248') throw new Error('Refusing source different from pinned 3.0.1 asset');
const {parse}=await import(pathToFileURL(parserPath).href);
const ast=parse(asset,{ecmaVersion:'latest',sourceType:'module'});
let usbClass;
function walk(node){
 if(!node||typeof node!=='object')return;
 if(node.type==='ClassExpression' && asset.slice(node.start,node.end).includes('Timed out waiting for response from HID device; re-trying'))usbClass=node;
 for(const v of Object.values(node))if(Array.isArray(v))v.forEach(walk);else if(v&&typeof v==='object')walk(v);
}
walk(ast);if(!usbClass) throw new Error('USB class not found');
const methods=['Y','H'].map(name=>{
 const method=usbClass.body.body.find(node=>node.key?.type==='PrivateIdentifier' && node.key.name===name);
 if(!method)throw new Error('Expected private method missing');
 return asset.slice(method.start,method.end);
}).join('\n');
const source=`class Harness { #s; #d; constructor(handle,events){this.#s=handle;this.#d=events;} #y(){} send(data){return this.#Y(data);} ${methods} }; Harness;`;
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
function setup(){
 let now=0;const timers=[],writes=[],events=new EventEmitter();
 const sleep=ms=>new Promise(resolve=>timers.push({at:now+ms,resolve}));
 const context=vm.createContext({xu:(a,n)=>Array.from({length:Math.ceil(a.length/n)},(_,i)=>a.slice(i*n,(i+1)*n)),lX:sleep},{codeGeneration:{strings:false,wasm:false}});
 const Harness=new vm.Script(source).runInContext(context,{timeout:100});
 const app=new Harness({write:async bytes=>{writes.push({at:now,length:bytes.length});return bytes.length;}},events);
 return {app,writes,events,timers,tick:async ms=>{now+=ms;for(const t of timers.splice(0))if(t.at<=now)t.resolve();else timers.push(t);await flush();},now:()=>now};
}
const packet=new Uint8Array(147);packet.set([2,0,144]);
const observe=p=>{let state={settled:false};p.then(()=>{state.settled=true;state.success=true;},e=>{state.settled=true;state.success=false;state.error=e.message;});return state;};
const results=[];
{
 const x=setup(),s=observe(x.app.send(packet));await flush();assert.deepEqual(x.writes.map(w=>w.length),[65,65,20]);assert(!s.settled);
 await x.tick(5);x.events.emit('130',new Uint8Array([130,0,1,0]));await flush();assert(s.success);assert(x.timers.length===1);
 results.push({case:'early_ack',writes:x.writes,settled_at_ms:x.now(),success:s.success,remaining_timeout_timer_does_not_delay_resolution:true});
}
{
 const x=setup(),s=observe(x.app.send(packet));await flush();await x.tick(1000);assert.equal(x.writes.length,6);assert(!s.settled);await x.tick(1000);assert(s.settled&&!s.success&&s.error==='Timeout');
 results.push({case:'missing_ack',write_reports:x.writes.length,settled_at_ms:x.now(),error:s.error});
}
{
 const x=setup(),s=observe(x.app.send(packet));await flush();x.events.emit('130',new Uint8Array([130,0,1,1]));await flush();assert(s.settled&&!s.success);results.push({case:'error_ack',rejected:true});
}
{
 const x=setup(),s=observe(x.app.send(packet));await flush();x.events.emit('137',new Uint8Array([137,0,1,0]));await flush();assert(!s.settled);x.events.emit('130',new Uint8Array([130,0,1,0]));await flush();assert(s.success);results.push({case:'other_command_ack',ignored_until_expected_type:true});
}
{
 const x=setup(),a=observe(x.app.send(packet)),b=observe(x.app.send(packet));await flush();x.events.emit('130',new Uint8Array([130,0,1,0]));await flush();assert(a.success&&b.success);results.push({case:'bypass_serial_queue_with_two_same_command_requests',one_ack_settles_both:true,limitation:'Mock demonstrates missing per-frame correlation, not physical device behaviour; vendor queue normally prevents this.'});
}
console.log(JSON.stringify({scope:'Selected vendor transport methods in JS VM with fake HID, event emitter and manually advanced clock only; no vendor app launch, USB or network',cases:results},null,2));
