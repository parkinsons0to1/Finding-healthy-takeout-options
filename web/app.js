'use strict';

const $ = (id) => document.getElementById(id);
const statusEl = $('status');
const resultsEl = $('results');
const dealsEl = $('mealdeals');
const contextEl = $('context');
const tabsEl = $('tabs');

let lastQuery = null;

function setStatus(msg, isError = false) {
  statusEl.textContent = msg;
  statusEl.classList.toggle('error', isError);
}

function selectedDiet() {
  return [...document.querySelectorAll('#dietChips input:checked')].map((i) => i.value);
}

function params() {
  return {
    diet: selectedDiet().join(','),
    min_protein_share: (Number($('share').value) / 100).toFixed(2),
    radius: $('radius').value,
    sort_by: $('sortBy').value,
    strict_halal: $('strictHalal').checked ? '1' : '0',
    limit: '25',
  };
}

function halalPill(status, tier) {
  if (status === 'halal') {
    const label = tier === 'brand_per_outlet' ? 'Halal — this branch'
      : tier === 'certifier_registry' ? 'Halal — certified'
      : 'Halal — chain-wide';
    return `<span class="pill halal" title="Evidence: ${tier}">${label}</span>`;
  }
  if (status === 'not_halal') return '';
  return '<span class="pill unverified" title="No source could confirm this — ask in store">Halal unverified</span>';
}

function itemCard(item, i) {
  const share = Math.round(item.protein_share * 100);
  const discounted = item.discount_label && item.final_price_gbp < item.list_price_gbp;
  const price = discounted
    ? `<s>£${item.list_price_gbp.toFixed(2)}</s> <strong>£${item.final_price_gbp.toFixed(2)}</strong>`
    : `<strong>£${item.final_price_gbp.toFixed(2)}</strong>`;
  const metric = $('sortBy').value === 'kcal_per_pound'
    ? { value: item.kcal_per_pound, unit: 'kcal / £' }
    : { value: item.protein_per_pound, unit: 'g protein / £' };

  return `<article class="card">
    <div class="rank">${i}</div>
    <div>
      <h3>${escapeHtml(item.name)}</h3>
      <div class="where">${escapeHtml(item.outlet_name)} · ${item.distance_miles} mi</div>
      <div class="macros">
        <span class="pill good">${item.protein_g}g protein</span>
        <span class="pill">${Math.round(item.kcal)} kcal</span>
        <span class="pill ${share >= 35 ? 'good' : ''}">${share}% of kcal</span>
        ${halalPill(item.halal_status, item.halal_tier)}
        ${item.vegan ? '<span class="pill good">Vegan</span>'
          : item.vegetarian ? '<span class="pill good">Vegetarian</span>' : ''}
        ${item.price_basis === 'estimated' ? '<span class="pill est">Price estimated</span>' : ''}
      </div>
      ${discounted ? `<div class="macros"><span class="pill deal">${escapeHtml(item.discount_label)}</span></div>` : ''}
    </div>
    <div class="score">
      <span class="big">${metric.value ?? '—'}</span>
      <span class="unit">${metric.unit}</span>
      <div class="price">${price}</div>
    </div>
  </article>`;
}

function bundleCard(b, i) {
  const share = Math.round(b.protein_share * 100);
  return `<article class="card">
    <div class="rank">${i}</div>
    <div>
      <h3>${escapeHtml(b.retailer)} ${escapeHtml(b.deal)}</h3>
      <div class="where">
        ${escapeHtml(b.main_name)} + ${escapeHtml(b.snack_name)} + ${escapeHtml(b.drink_name)}
      </div>
      <div class="macros">
        <span class="pill good">${b.protein_g}g protein</span>
        <span class="pill">${Math.round(b.kcal)} kcal</span>
        <span class="pill ${share >= 35 ? 'good' : ''}">${share}% of kcal</span>
        <span class="pill">Fixed price</span>
      </div>
    </div>
    <div class="score">
      <span class="big">${b.protein_per_pound}</span>
      <span class="unit">g protein / £</span>
      <div class="price"><strong>£${b.price_gbp.toFixed(2)}</strong></div>
    </div>
  </article>`;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function runSearch(query) {
  lastQuery = query;
  const qs = new URLSearchParams({ ...params(), ...query });
  setStatus('Finding outlets near you and checking every menu…');
  resultsEl.innerHTML = '';
  contextEl.hidden = true;

  try {
    const res = await fetch(`/api/search?${qs}`);
    const data = await res.json();
    if (data.error) return setStatus(data.error, true);
    render(data);
    loadMealDeals();
  } catch (err) {
    setStatus(`Search failed: ${err.message}`, true);
  }
}

function render(data) {
  const loc = data.location || {};
  const where = loc.postcode || `${loc.lat?.toFixed(3)}, ${loc.lng?.toFixed(3)}`;
  const c = data.counts || {};
  setStatus(`${where}${loc.district ? ` · ${loc.district}` : ''} — ` +
    `${data.outlet_counts.chains} chain outlets nearby, ` +
    `${c.qualifying} of ${c.eligible} items meet your filters.`);

  tabsEl.hidden = false;

  if (!data.results.length) {
    // Distinguish "no chains here at all" (rural/coastal towns) from "chains
    // are here but nothing clears your filters" — they need different advice.
    const noChains = data.outlet_counts.chains === 0;
    const radius = Number($('radius').value);
    resultsEl.innerHTML = `<div class="empty">
      ${noChains
        ? `<strong>No chain outlets within ${radius} mile${radius === 1 ? '' : 's'}.</strong>
           <p>We found ${data.outlet_counts.independents} independent places and
           ${data.outlet_counts.supermarkets} supermarket(s) here, but independents
           don't publish nutrition data — they're under the UK calorie-labelling
           threshold — so we can't rank them yet.</p>
           <p>Your best bets: check the <strong>Meal deals</strong> tab
           ${data.outlet_counts.supermarkets ? '(there are supermarkets nearby)' : ''},
           or widen the radius to reach the nearest chains.</p>
           ${radius < 5 ? '<button class="btn" id="widen">Search 5 miles instead</button>' : ''}`
        : `Nothing here clears that protein bar. Try lowering the protein slider
           or widening the radius — or check the Meal deals tab.`}
    </div>`;
    const widen = $('widen');
    if (widen) {
      widen.addEventListener('click', () => {
        $('radius').value = 5;
        $('radiusOut').textContent = '5 miles';
        if (lastQuery) runSearch(lastQuery);
      });
    }
  } else {
    resultsEl.innerHTML = data.results.map((r, i) => itemCard(r, i + 1)).join('');
  }

  if (data.near_misses?.length) {
    resultsEl.insertAdjacentHTML('beforeend',
      `<h2 class="section-head">Just below your threshold — often the best value</h2>` +
      data.near_misses.map((m, i) => itemCard(m, i + 1)).join(''));
  }

  const unverified = data.outlets.filter((o) => o.halal_status === 'unverified').length;
  contextEl.hidden = false;
  contextEl.innerHTML =
    `Searched ${data.outlet_counts.total} food businesses within your radius: ` +
    `${data.outlet_counts.chains} chains with published nutrition, ` +
    `${data.outlet_counts.independents} independents (no published macros yet), ` +
    `${data.outlet_counts.supermarkets} supermarkets.` +
    (unverified ? ` ${unverified} outlet(s) have unverified halal status.` : '');
}

async function loadMealDeals() {
  try {
    const qs = new URLSearchParams({
      diet: selectedDiet().join(','),
      min_protein_share: (Number($('share').value) / 100).toFixed(2),
    });
    const res = await fetch(`/api/mealdeals?${qs}`);
    const data = await res.json();
    dealsEl.innerHTML = data.bundles?.length
      ? data.bundles.map((b, i) => bundleCard(b, i + 1)).join('')
      : `<div class="empty">${escapeHtml(data.note || 'No meal deal bundles matched those filters.')}</div>`;
  } catch {
    dealsEl.innerHTML = '<div class="empty">Meal deal data unavailable.</div>';
  }
}

function showPlaceChoices(places, query) {
  resultsEl.innerHTML =
    `<h2 class="section-head">Which ${escapeHtml(query)}?</h2>` +
    places.map((p) => `<button class="btn place" data-lat="${p.lat}" data-lng="${p.lng}">
        ${escapeHtml(p.label)}
      </button>`).join('');
  setStatus(`"${query}" matches ${places.length} places — pick one.`);
  resultsEl.querySelectorAll('.place').forEach((btn) =>
    btn.addEventListener('click', () =>
      runSearch({ lat: btn.dataset.lat, lng: btn.dataset.lng })));
}

async function submitQuery() {
  const text = $('postcode').value.trim();
  if (!text) return setStatus('Enter a postcode or place, or use your location.', true);

  // A postcode is unambiguous; a place name often isn't ("St Ives" matches
  // Cornwall, Cambridgeshire and Dorset), so ask rather than guess.
  try {
    const res = await fetch(`/api/places?q=${encodeURIComponent(text)}`);
    const data = await res.json();
    if (data.is_postcode) return runSearch({ postcode: text });
    if (!data.places.length) {
      return setStatus(`Couldn't find "${text}". Try a postcode instead.`, true);
    }
    if (data.places.length === 1) {
      const p = data.places[0];
      return runSearch({ lat: p.lat, lng: p.lng });
    }
    tabsEl.hidden = true;
    return showPlaceChoices(data.places, text);
  } catch {
    return runSearch({ postcode: text });
  }
}

$('go').addEventListener('click', submitQuery);

$('postcode').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('go').click();
});

$('useLocation').addEventListener('click', () => {
  if (!navigator.geolocation) {
    return setStatus('This browser has no location support — type a postcode instead.', true);
  }
  setStatus('Asking for your location…');
  // On iOS/macOS Safari this permission prompt is served by Apple's Core Location.
  navigator.geolocation.getCurrentPosition(
    (pos) => runSearch({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
    (err) => setStatus(
      err.code === err.PERMISSION_DENIED
        ? 'Location permission denied — type a postcode instead.'
        : `Could not get your location: ${err.message}`, true),
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
});

$('share').addEventListener('input', (e) => {
  $('shareOut').textContent = `${e.target.value}%`;
});
$('radius').addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('radiusOut').textContent = v === 1 ? '1 mile' : `${v} miles`;
});

for (const el of [$('sortBy'), $('strictHalal'), $('share'), $('radius')]) {
  el.addEventListener('change', () => { if (lastQuery) runSearch(lastQuery); });
}
document.querySelectorAll('#dietChips input').forEach((i) =>
  i.addEventListener('change', () => { if (lastQuery) runSearch(lastQuery); }));

tabsEl.addEventListener('click', (e) => {
  const tab = e.target.closest('.tab');
  if (!tab) return;
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === tab));
  const takeaway = tab.dataset.tab === 'takeaway';
  resultsEl.hidden = !takeaway;
  contextEl.hidden = !takeaway;
  dealsEl.hidden = takeaway;
});
