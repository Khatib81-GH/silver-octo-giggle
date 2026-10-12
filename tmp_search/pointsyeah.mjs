import crypto from 'node:crypto';
import fs from 'node:fs';

const API_BASE = 'https://api2.pointsyeah.com';
const KEY_PREFIX = 'LefjQ2pEXmiy/nNZvhJ43i8';
const KEY_SUFFIX = 'YHYbn1hOuAgA=';
const DEFAULT_KEY_SECTION = 'hJuaknzb';
const STATIC_IV = Buffer.from('1020304050607080', 'utf8');

const headers = {
  'content-type': 'application/json',
  'origin': 'https://www.pointsyeah.com',
  'referer': 'https://www.pointsyeah.com/',
  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
  'accept': 'application/json, text/plain, */*',
};

function buildKey(section) {
  return Buffer.from(KEY_PREFIX + section + KEY_SUFFIX, 'base64');
}

function encryptPayload(plaintext, section = DEFAULT_KEY_SECTION) {
  const cipher = crypto.createCipheriv('aes-256-cbc', buildKey(section), STATIC_IV);
  return Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]).toString('base64');
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function routeSummary(programResult, route) {
  const segs = (route.segments || []).map(s => ({
    flight_number: s.flight_number,
    aircraft: s.aircraft,
    departs: s.dt,
    from: s.da,
    arrives: s.at,
    to: s.aa,
    layover_minutes: s.layover,
    cabin: s.cabin,
    duration_minutes: s.duration,
  }));
  return {
    date: programResult.date,
    award_program: programResult.program,
    award_code: programResult.code,
    origin: programResult.departure,
    destination: programResult.arrival,
    miles: route.payment?.miles ?? null,
    taxes: route.payment?.tax ?? null,
    currency: route.payment?.currency ?? null,
    cabin: route.payment?.cabin ?? null,
    seats: route.payment?.seats ?? null,
    cash_price: route.payment?.cash_price ?? null,
    total_duration_minutes: route.duration ?? null,
    cross_days: route.cross_days ?? null,
    booking_url: route.url ?? null,
    cash_ticket_url: route.cash_ticket_url ?? null,
    booking_code: route.extra?.booking_code ?? null,
    segments: segs,
  };
}

const plaintext = JSON.stringify({
  search_type: 'one_way',
  cabins: ['Economy'],
  segments: [{
    arrival: 'DTW',
    departure: 'JED',
    departure_date: { from: '2026-12-25', to: '2027-01-05' },
  }],
  passengers_v2: { adults: 1, children: 0 },
  source: 'mobile',
});
const data = encryptPayload(plaintext);

console.log('Creating PointsYeah task...');
const createResp = await fetch(`${API_BASE}/flight/search/create_task`, {
  method: 'POST', headers, body: JSON.stringify({ data, encrypted: data }),
});
const createText = await createResp.text();
console.log('create_task status', createResp.status, createText.slice(0, 1000));
if (!createResp.ok) throw new Error(`create_task ${createResp.status}: ${createText}`);
const created = JSON.parse(createText);
const taskId = created?.data?.task_id;
if (!taskId) throw new Error(`No task id: ${createText}`);

const merged = new Map();
let lastStatus = '';
for (let i = 0; i < 50; i++) {
  const resp = await fetch(`${API_BASE}/flight/search/fetch_result`, {
    method: 'POST', headers, body: JSON.stringify({ task_id: taskId }),
  });
  const text = await resp.text();
  if (!resp.ok) throw new Error(`fetch_result ${resp.status}: ${text}`);
  const snap = JSON.parse(text);
  lastStatus = snap?.data?.status || '';
  for (const r of snap?.data?.result || []) {
    const key = `${r.code}|${r.date}|${r.departure}|${r.arrival}`;
    const old = merged.get(key);
    if (!old || (r.routes?.length || 0) > (old.routes?.length || 0)) merged.set(key, r);
  }
  console.log(`poll ${i + 1}: status=${lastStatus}, program/date groups=${merged.size}`);
  if (['done', 'completed'].includes(lastStatus)) break;
  await sleep(500);
}

const raw = [...merged.values()];
fs.writeFileSync('pointsyeah_raw.json', JSON.stringify({ status: lastStatus, results: raw }, null, 2));

const summaries = raw.flatMap(r => (r.routes || []).map(route => routeSummary(r, route)));
const skyTeamCodes = new Set(['AR','AM','UX','CI','MU','OK','GA','KQ','KE','ME','SV','RO','VN','MF','AF','KL','DL','VS','SK']);
function segmentCarrier(s) {
  const m = String(s.flight_number || '').trim().match(/^([A-Z0-9]{2})/i);
  return m ? m[1].toUpperCase() : '';
}
function allSkyTeam(x) {
  return x.segments.length > 0 && x.segments.every(s => skyTeamCodes.has(segmentCarrier(s)));
}
function relevantProgram(x) {
  const p = `${x.award_program || ''} ${x.award_code || ''}`.toLowerCase();
  return p.includes('flying blue') || p.includes('delta') || p.includes('skymiles') || ['AF','FB','DL'].includes(String(x.award_code || '').toUpperCase());
}

const filtered = summaries.filter(x => relevantProgram(x) && allSkyTeam(x));
filtered.sort((a,b) => String(a.date).localeCompare(String(b.date)) || (a.miles ?? 1e15) - (b.miles ?? 1e15));
fs.writeFileSync('pointsyeah_filtered.json', JSON.stringify(filtered, null, 2));

const programs = [...new Set(summaries.map(x => `${x.award_program} [${x.award_code}]`))].sort();
console.log('Programs returned:', programs.join(' | '));
console.log(`Total routes=${summaries.length}; relevant all-SkyTeam routes=${filtered.length}`);
console.log('POINTSYEAH_FILTERED_BEGIN');
console.log(JSON.stringify(filtered));
console.log('POINTSYEAH_FILTERED_END');
