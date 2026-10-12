import fs from 'node:fs';
import crypto from 'node:crypto';
import { chromium } from 'playwright';

const DATES = [];
for (let d = new Date('2026-12-25T00:00:00Z'); d <= new Date('2027-01-05T00:00:00Z'); d.setUTCDate(d.getUTCDate() + 1)) {
  DATES.push(d.toISOString().slice(0, 10));
}

const QUERY = [
  'query ($offerSearchCriteria: OfferSearchCriteriaInput!) {',
  'gqlSearchOffers(offerSearchCriteria: $offerSearchCriteria) {',
  'offerResponseId gqlOffersSets {',
  'trips { tripId scheduledDepartureLocalTs scheduledArrivalLocalTs',
  'originAirportCode destinationAirportCode stopCnt',
  'totalTripTime { dayCnt hourCnt minuteCnt }',
  'flightSegment {',
  'marketingCarrier { carrierCode carrierNum }',
  'operatingCarrier { carrierCode carrierNum }',
  'flightLeg { legId',
  'marketingCarrier { carrierCode carrierNum }',
  'operatingCarrier { carrierCode carrierNum }',
  'aircraft { fleetTypeCode subFleetTypeCode }',
  'duration { dayCnt hourCnt minuteCnt }',
  'layover { destinationAirportCode layoverDuration { dayCnt hourCnt minuteCnt } } } } }',
  'offers { offerId',
  'additionalOfferProperties { fareType dominantSegmentBrandId }',
  'offerItems { retailItems { retailItemMetaData { fareInformation {',
  'brandByFlightLegs { brandId cosCode } availableSeatCnt',
  'farePrice { totalFarePrice { milesEquivalentPrice { mileCnt }',
  'currencyEquivalentPrice { roundedCurrencyAmt currencyCode } } } } } } } } } } }'
].join(' ');

function requestBody(date) {
  return {
    variables: {
      offerSearchCriteria: {
        productGroups: [{ productCategoryCode: 'FLIGHTS' }],
        offersCriteria: {
          resultsPageNum: 1,
          resultsPerRequestNum: 50,
          preferences: {
            refundableOnly: false,
            showGlobalRegionalUpgradeCertificate: true,
            nonStopOnly: false,
            excludeBrandTypes: [],
          },
          pricingCriteria: { priceableIn: ['MILES'] },
          flightRequestCriteria: {
            currentTripIndexId: '0',
            sortableOptionId: null,
            selectedOfferId: '',
            searchOriginDestination: [{
              departureLocalTs: `${date}T00:00:00`,
              destinations: [{ airportCode: 'DTW' }],
              origins: [{ airportCode: 'JED' }],
            }],
            sortByBrandId: 'MAIN',
            additionalCriteriaMap: { rollOutTag: 'GBB' },
          },
        },
        customers: [{ passengerTypeCode: 'ADT', passengerId: '1' }],
      },
    },
    query: QUERY,
  };
}

function durationMins(x) {
  if (!x || typeof x !== 'object') return null;
  return Number(x.dayCnt || 0) * 1440 + Number(x.hourCnt || 0) * 60 + Number(x.minuteCnt || 0);
}

function fareInfos(offer) {
  const out = [];
  for (const oi of offer?.offerItems || []) {
    for (const ri of oi?.retailItems || []) {
      for (const fi of ri?.retailItemMetaData?.fareInformation || []) out.push(fi);
    }
  }
  return out;
}

function parseDate(date, raw) {
  const rows = [];
  const sets = raw?.data?.gqlSearchOffers?.gqlOffersSets || [];
  for (const set of sets) {
    const trip = (set.trips || [])[0] || {};
    const segments = (trip.flightSegment || []).map(seg => ({
      marketing: `${seg?.marketingCarrier?.carrierCode || ''}${seg?.marketingCarrier?.carrierNum || ''}`,
      operating: `${seg?.operatingCarrier?.carrierCode || ''}${seg?.operatingCarrier?.carrierNum || ''}`,
      legs: (seg.flightLeg || []).map(leg => ({
        marketing: `${leg?.marketingCarrier?.carrierCode || ''}${leg?.marketingCarrier?.carrierNum || ''}`,
        operating: `${leg?.operatingCarrier?.carrierCode || ''}${leg?.operatingCarrier?.carrierNum || ''}`,
        aircraft: leg?.aircraft?.fleetTypeCode || leg?.aircraft?.subFleetTypeCode || null,
        duration_minutes: durationMins(leg?.duration),
        layover_airport: leg?.layover?.destinationAirportCode || null,
        layover_minutes: durationMins(leg?.layover?.layoverDuration),
      })),
    }));
    for (const offer of set.offers || []) {
      for (const fi of fareInfos(offer)) {
        let fp = fi?.farePrice;
        if (Array.isArray(fp)) fp = fp[0];
        const total = fp?.totalFarePrice || {};
        const miles = total?.milesEquivalentPrice?.mileCnt;
        const cash = total?.currencyEquivalentPrice?.roundedCurrencyAmt;
        if (!(Number(miles) > 0)) continue;
        rows.push({
          date,
          departure: trip.scheduledDepartureLocalTs || null,
          arrival: trip.scheduledArrivalLocalTs || null,
          stops: Number.isInteger(trip.stopCnt) ? trip.stopCnt : null,
          duration_minutes: durationMins(trip.totalTripTime),
          miles: Number(miles),
          taxes_fees: typeof cash === 'number' ? cash : Number(cash) || null,
          currency: total?.currencyEquivalentPrice?.currencyCode || 'USD',
          fare_type: offer?.additionalOfferProperties?.fareType || null,
          dominant_brand: offer?.additionalOfferProperties?.dominantSegmentBrandId || null,
          brands: fi?.brandByFlightLegs || [],
          available_seats: fi?.availableSeatCnt ?? null,
          segments,
        });
      }
    }
  }
  rows.sort((a, b) => a.miles - b.miles || (a.taxes_fees ?? 1e9) - (b.taxes_fees ?? 1e9));
  return rows;
}

const browser = await chromium.launch({
  headless: false,
  args: ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
});
const context = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
  locale: 'en-US',
});
const page = await context.newPage();
const output = [];
try {
  console.log('Warming delta.com...');
  await page.goto('https://www.delta.com/', { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(8000);
  console.log('Warm page:', await page.title());
  for (const date of DATES) {
    console.log('Delta SkyMiles', date);
    try {
      const body = requestBody(date);
      const result = await page.evaluate(async ({ body, transactionId }) => {
        const resp = await fetch('https://offer-api-prd.delta.com/prd/rm-offer-gql', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'accept': 'application/json',
            'content-type': 'application/json',
            'airline': 'DL',
            'applicationid': 'DC',
            'authorization': 'GUEST',
            'channelid': 'DCOM',
            'transactionid': transactionId,
            'x-app-route': 'search',
            'x-app-type': 'dcom-shop',
          },
          body: JSON.stringify(body),
        });
        const text = await resp.text();
        return { status: resp.status, text };
      }, { body, transactionId: `${crypto.randomUUID()}_${Date.now()}` });
      if (result.status !== 200) {
        output.push({ date, error: `HTTP ${result.status}`, body_prefix: result.text.slice(0, 2000) });
        console.log('  HTTP', result.status, result.text.slice(0, 300));
      } else {
        const raw = JSON.parse(result.text);
        const rows = parseDate(date, raw);
        output.push({ date, rows, raw_error: raw.errors || null });
        console.log('  rows', rows.length, rows.slice(0, 3).map(x => `${x.miles}+${x.taxes_fees}`).join(', '));
      }
    } catch (err) {
      output.push({ date, error: `${err.name}: ${err.message}` });
      console.log('  ERROR', err);
    }
    await page.waitForTimeout(1500);
  }
} finally {
  await browser.close();
}
fs.writeFileSync('delta_awards.json', JSON.stringify(output, null, 2));
console.log('DELTA_AWARDS_BEGIN');
console.log(JSON.stringify(output));
console.log('DELTA_AWARDS_END');
