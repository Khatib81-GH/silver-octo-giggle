import fs from 'node:fs';
import { chromium } from 'playwright';

const targets = [
  {
    name: 'airfrance_reward',
    url: 'https://wwws.airfrance.us/search/offers?activeConnection=0&bookingFlow=REWARD&cabinClass=ECONOMY&pax=1:0:0:0:0:0:0:0&connections=JED:C:20261225%3EDTW',
  },
  {
    name: 'klm_reward',
    url: 'https://www.klm.com/search/offers?activeConnection=0&bookingFlow=REWARD&cabinClass=ECONOMY&pax=1:0:0:0:0:0:0:0&connections=JED:C:20261225%3EDTW',
  },
  {
    name: 'klm_alt',
    url: 'https://www.klm.com/search/offers?pax=ADT:1&origin=JED&destination=DTW&outwardDate=20261225&cabin=economy&bookingFlow=REWARD',
  },
];

const browser = await chromium.launch({ headless: false, args: ['--disable-blink-features=AutomationControlled', '--no-sandbox'] });
const output = [];
try {
  for (const target of targets) {
    const context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
      locale: 'en-US',
      viewport: { width: 1440, height: 1100 },
    });
    const page = await context.newPage();
    const events = [];
    const pending = [];
    page.on('request', req => {
      const u = req.url();
      if (/offer|search|flight|award|miles|avail|booking|shopping/i.test(u)) {
        events.push({ type: 'request', method: req.method(), url: u, postData: (req.postData() || '').slice(0, 10000) });
      }
    });
    page.on('response', resp => {
      const u = resp.url();
      const ct = resp.headers()['content-type'] || '';
      if (/offer|search|flight|award|miles|avail|booking|shopping/i.test(u) || ct.includes('json')) {
        const p = (async () => {
          let body = '';
          try {
            body = await resp.text();
          } catch {}
          events.push({ type: 'response', status: resp.status(), url: u, contentType: ct, body: body.slice(0, 50000) });
        })();
        pending.push(p);
      }
    });
    let navError = null;
    try {
      console.log('Opening', target.name, target.url);
      await page.goto(target.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
      await page.waitForTimeout(20000);
    } catch (e) {
      navError = `${e.name}: ${e.message}`;
    }
    await Promise.allSettled(pending);
    const bodyText = (await page.locator('body').innerText().catch(() => '')).slice(0, 30000);
    await page.screenshot({ path: `${target.name}.png`, fullPage: true }).catch(() => {});
    output.push({
      name: target.name,
      requestedUrl: target.url,
      finalUrl: page.url(),
      title: await page.title().catch(() => ''),
      navError,
      bodyText,
      events,
    });
    console.log(target.name, 'final', page.url(), 'events', events.length, 'text', bodyText.slice(0, 500));
    await context.close();
  }
} finally {
  await browser.close();
}
fs.writeFileSync('afklm_probe.json', JSON.stringify(output, null, 2));
console.log('AFKLM_PROBE_BEGIN');
console.log(JSON.stringify(output.map(x => ({name:x.name, finalUrl:x.finalUrl, title:x.title, navError:x.navError, bodyText:x.bodyText.slice(0,1000), eventCount:x.events.length}))));
console.log('AFKLM_PROBE_END');
