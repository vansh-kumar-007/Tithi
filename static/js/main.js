/**
 * Hindu Tithi Birthday Calculator — Main JS
 */
'use strict';

// ══════════════════════════════════════════════════════
// Helpers & Bilingual Dictionaries
// ══════════════════════════════════════════════════════
let currentLang = 'en';
let lastResult = null;
let selectedCandidateIdx = 0;
let loadingTimers = [];
let activeSavedProfileId = null;

function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
window.escapeHtml = escapeHtml;

const I18N = {
  en: {
    resultsHeroTitle: 'Your Hindu Panchang',
    noticePrefix: 'Important Notice:',
    nextBirthday: 'Next Hindu Birthday',
    todayBirthday: 'TODAY IS YOUR HINDU BIRTHDAY!',
    daysFromToday: 'day(s) from today',
    birthInfoHeader: 'Birth Information & Birth Panchang',
    dob: 'Date of Birth',
    birthTime: 'Birth Time',
    birthplace: 'Birthplace',
    coords: 'Coordinates',
    timezone: 'Timezone',
    sunrise: 'Sunrise',
    sunset: 'Sunset',
    ayanamsha: 'Ayanamsha',
    conventions: 'Conventions',
    panchangElements: 'Panchang Elements',
    tithi: 'Tithi',
    tithiAtSunrise: 'Tithi at Sunrise',
    sunriseRef: 'Traditional observance reference',
    nakshatra: 'Nakshatra',
    yoga: 'Yoga',
    karana: 'Karana',
    lunarMonth: 'Lunar Month',
    calendarHeader: 'Hindu Birthday Calendar',
    visualTitle: 'Year-by-Year Visual Calendar',
    colYear: 'Year',
    colDate: 'Hindu Birthday',
    colDay: 'Weekday',
    colMonth: 'Lunar Month',
    colTithi: 'Tithi',
    colStart: 'Tithi Starts',
    colEnd: 'Tithi Ends',
    colStatus: 'Status',
    colNotes: 'Notes',
    dlCsv: 'Download CSV',
    dlExcel: 'Download Excel',
    dlPdf: 'Download PDF',
    dlIcs: 'Add to Calendar (ICS)',
    printBtn: 'Print',
    recalcBtn: 'Recalculate with Different Details',
    candidatePrompt: 'Select Candidate Tithi Calendar:',
    unknownTime: 'Unknown (Full Local Day)',
    optionLabel: 'Option',
    saveProfileBtn: 'Save Birth Profile',
    saveHistoryBtn: 'Save to Calculation History',
    cloudSavePrompt: 'Save this profile or calculation to your account:',
    loginToSavePrompt: 'Want to save this birth profile or calculation?',
    loginToSaveBtn: 'Log In / Sign Up to Save',
  },
  hi: {
    resultsHeroTitle: 'आपका हिंदू पंचांग',
    noticePrefix: 'महत्वपूर्ण सूचना:',
    nextBirthday: 'अगला हिंदू जन्मदिन',
    todayBirthday: 'आज आपका हिंदू जन्मदिन है!',
    daysFromToday: 'दिन शेष',
    birthInfoHeader: 'जन्म विवरण और जन्म पंचांग',
    dob: 'जन्म तिथि',
    birthTime: 'जन्म समय',
    birthplace: 'जन्मस्थान',
    coords: 'निर्देशांक',
    timezone: 'समय क्षेत्र',
    sunrise: 'सूर्योदय',
    sunset: 'सूर्यास्त',
    ayanamsha: 'अयनांश',
    conventions: 'गणना परंपरा',
    panchangElements: 'पंचांग के अंग',
    tithi: 'तिथि',
    tithiAtSunrise: 'सूर्योदय तिथि',
    sunriseRef: 'पारंपरिक उत्सव संदर्भ',
    nakshatra: 'नक्षत्र',
    yoga: 'योग',
    karana: 'करण',
    lunarMonth: 'चंद्र मास',
    calendarHeader: 'हिंदू जन्मदिन कैलेंडर',
    visualTitle: 'वर्ष-वार दृश्य कैलेंडर',
    colYear: 'वर्ष',
    colDate: 'हिंदू जन्मदिन',
    colDay: 'वार',
    colMonth: 'चंद्र मास',
    colTithi: 'तिथि',
    colStart: 'तिथि प्रारंभ',
    colEnd: 'तिथि समाप्त',
    colStatus: 'स्थिति',
    colNotes: 'टिप्पणी',
    dlCsv: 'CSV डाउनलोड',
    dlExcel: 'Excel डाउनलोड',
    dlPdf: 'PDF डाउनलोड',
    dlIcs: 'कैलेंडर (ICS)',
    printBtn: 'प्रिंट करें',
    recalcBtn: 'अन्य विवरण से पुनः गणना करें',
    candidatePrompt: 'संभावित तिथि कैलेंडर चुनें:',
    unknownTime: 'अज्ञात (संपूर्ण दिन का विश्लेषण)',
    optionLabel: 'विकल्प',
    saveProfileBtn: 'जन्म प्रोफ़ाइल सहेजें',
    saveHistoryBtn: 'गणना इतिहास में सहेजें',
    cloudSavePrompt: 'इस प्रोफ़ाइल या गणना को अपने खाते में सहेजें:',
    loginToSavePrompt: 'क्या आप यह जन्म प्रोफ़ाइल या गणना सहेजना चाहते हैं?',
    loginToSaveBtn: 'सहेजने के लिए लॉग इन / साइन अप करें',
  },
};

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N.en[key] || key;
}

function setLang(lang) {
  currentLang = lang;
  document.querySelectorAll('[data-' + lang + ']').forEach(el => {
    el.textContent = el.getAttribute('data-' + lang);
  });
  document.querySelectorAll('.btn-lang').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('btn-lang-' + lang);
  if (btn) btn.classList.add('active');
  localStorage.setItem('tithi_lang', lang);

  if (lastResult) {
    renderResults(lastResult);
  }
  if (window.TithiAuth && typeof window.TithiAuth.onLanguageChange === 'function') {
    window.TithiAuth.onLanguageChange(lang);
  }
}

// ══════════════════════════════════════════════════════
// Geocoding & Location Selection
// ══════════════════════════════════════════════════════
let geocodeDebounce = null;

async function geocodeLocation(query) {
  const status = document.getElementById('geocode-status');
  const trimmed = (query || '').trim();
  if (!trimmed) return null;

  status.innerHTML = '<span class="geocode-loading"><i class="fas fa-spinner fa-spin me-1"></i>Searching…</span>';

  try {
    const resp = await fetch('/geocode?q=' + encodeURIComponent(trimmed));
    const data = await resp.json();
    if (!resp.ok || data.error) {
      status.innerHTML = `<span class="geocode-error"><i class="fas fa-times-circle me-1"></i>${escapeHtml(data.error || 'Location not found.')}</span>`;
      return null;
    }
    setLocation(data);
    status.innerHTML = `<span class="geocode-success"><i class="fas fa-check-circle me-1"></i>${escapeHtml(data.display_name)}</span>`;
    return data;
  } catch (err) {
    status.innerHTML = '<span class="geocode-error"><i class="fas fa-exclamation-circle me-1"></i>Geocoding failed. Check connection or use Quick Pick / Manual coordinates.</span>';
    return null;
  }
}

function setLocation(data) {
  document.getElementById('lat').value = data.lat;
  document.getElementById('lon').value = data.lon;
  document.getElementById('timezone').value = data.timezone;
  document.getElementById('location_name').value = data.display_name || data.city || '';
  document.getElementById('lat-display').textContent = parseFloat(data.lat).toFixed(4) + '°';
  document.getElementById('lon-display').textContent = parseFloat(data.lon).toFixed(4) + '°';
  document.getElementById('tz-display').textContent = data.timezone;
  document.getElementById('coords-display').style.display = 'block';
  document.getElementById('location_query')?.classList.remove('is-invalid');
}

function clearLocationSelection() {
  document.getElementById('lat').value = '';
  document.getElementById('lon').value = '';
  document.getElementById('timezone').value = '';
  document.getElementById('location_name').value = '';
  document.getElementById('coords-display').style.display = 'none';
}

// ══════════════════════════════════════════════════════
// Birth Time Mode & Convention Explanation
// ══════════════════════════════════════════════════════
function switchTimeMode(mode) {
  document.querySelectorAll('.time-mode-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.time-panel').forEach(p => { p.style.display = 'none'; });
  document.getElementById('birth_time_mode').value = mode;

  const btn = document.querySelector('[data-mode="' + mode + '"]');
  if (btn) btn.classList.add('active');
  const panel = document.getElementById('panel-' + mode);
  if (panel) panel.style.display = '';
}

function updateConventionExplanation() {
  const sys = document.getElementById('lunar_system')?.value || 'amanta';
  const obs = document.getElementById('observance_method')?.value || 'sunrise';
  const adh = document.getElementById('adhika_rule')?.value || 'nija';
  const el = document.getElementById('convention-explanation');
  if (!el) return;

  const obsText = {
    sunrise: 'local sunrise (Udaya Tithi)',
    madhyahna: 'local solar midday (Madhyahna)',
    sunset: 'local sunset (Sayahna)',
  }[obs] || obs;

  const sysText = sys === 'purnimanta'
    ? 'Purnimanta (Full Moon to Full Moon)'
    : 'Amanta (New Moon to New Moon)';

  const adhText = {
    nija: 'regular (Nija) lunar month',
    adhika: 'Adhika Masa when present (falling back to regular month otherwise)',
    both: 'both regular and Adhika lunar months when present',
  }[adh] || adh;

  el.innerHTML = `<i class="fas fa-info-circle text-saffron me-2"></i><strong>Convention:</strong> Annual birthdays are matched using the <strong>${escapeHtml(sysText)}</strong> calendar when your birth Tithi prevails at <strong>${escapeHtml(obsText)}</strong>, observing in the <strong>${escapeHtml(adhText)}</strong>.`;
}

// ══════════════════════════════════════════════════════
// DOM Initialization
// ══════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', function () {
  const savedLang = localStorage.getItem('tithi_lang');
  if (savedLang && savedLang !== 'en') setLang(savedLang);

  // Smooth scroll for hero Calculate Now button
  const heroBtn = document.getElementById('btn-hero-calculate');
  if (heroBtn) {
    heroBtn.addEventListener('click', e => {
      const target = document.getElementById('calculator');
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth' });
      }
    });
  }

  // Quick city chips
  document.querySelectorAll('.city-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const locInput = document.getElementById('location_query');
      if (locInput) locInput.value = chip.dataset.name;
      setLocation({
        display_name: chip.dataset.name,
        lat: parseFloat(chip.dataset.lat),
        lon: parseFloat(chip.dataset.lon),
        timezone: chip.dataset.tz,
      });
      document.getElementById('geocode-status').innerHTML =
        `<span class="geocode-success"><i class="fas fa-check-circle me-1"></i>${escapeHtml(chip.dataset.name)}</span>`;
    });
  });

  // Geocode button & input handlers
  const btnGeocode = document.getElementById('btn-geocode');
  const locInput = document.getElementById('location_query');
  if (btnGeocode && locInput) {
    btnGeocode.addEventListener('click', () => geocodeLocation(locInput.value));
  }
  if (locInput) {
    locInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        clearTimeout(geocodeDebounce);
        geocodeLocation(locInput.value);
      }
    });
    locInput.addEventListener('input', () => {
      // Clear stale hidden coords whenever the user edits location text
      clearLocationSelection();
      document.getElementById('geocode-status').innerHTML = '';
      clearTimeout(geocodeDebounce);
      geocodeDebounce = setTimeout(() => {
        if (locInput.value.trim().length > 2) geocodeLocation(locInput.value);
      }, 900);
    });
  }

  // Manual coordinates & timezone detection/override
  const btnManual = document.getElementById('btn-manual-coords');
  if (btnManual) {
    btnManual.addEventListener('click', async () => {
      const lat = parseFloat(document.getElementById('lat_manual').value);
      const lon = parseFloat(document.getElementById('lon_manual').value);
      let tzOverride = (document.getElementById('tz_manual').value || '').trim();

      if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
        showError('Please enter valid latitude (-90..90) and longitude (-180..180).');
        return;
      }

      if (!tzOverride) {
        try {
          const resp = await fetch(`/timezone?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`);
          const data = await resp.json();
          if (resp.ok && data.timezone) {
            tzOverride = data.timezone;
            document.getElementById('tz_manual').value = tzOverride;
          }
        } catch (e) {
          tzOverride = 'UTC';
        }
      }
      tzOverride = tzOverride || 'UTC';
      const label = document.getElementById('location_query').value.trim() || `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
      setLocation({ lat, lon, timezone: tzOverride, display_name: label });
      document.getElementById('geocode-status').innerHTML =
        `<span class="geocode-success"><i class="fas fa-check-circle me-1"></i>Manual coordinates applied (${escapeHtml(tzOverride)})</span>`;
    });
  }

  // Time mode tabs
  document.querySelectorAll('.time-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTimeMode(btn.dataset.mode));
  });

  // Period preset buttons
  document.querySelectorAll('.period-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('approx_start').value = btn.dataset.start;
      document.getElementById('approx_end').value = btn.dataset.end;
    });
  });

  // Convention dropdown updates
  ['lunar_system', 'observance_method', 'adhika_rule'].forEach(id => {
    document.getElementById(id)?.addEventListener('change', updateConventionExplanation);
  });
  updateConventionExplanation();

  // Main form submit & reset profile linkage on manual edits
  const form = document.getElementById('mainForm');
  if (form) {
    form.addEventListener('submit', handleFormSubmit);
    ['birth_date', 'location_query'].forEach(id => {
      document.getElementById(id)?.addEventListener('input', () => {
        activeSavedProfileId = null;
      });
    });
  }

  if (window.location.hash === '#calculator') {
    setTimeout(() => {
      document.getElementById('calculator')?.scrollIntoView({ behavior: 'smooth' });
    }, 300);
  }
});

// ══════════════════════════════════════════════════════
// Form Submission & Calculation
// ══════════════════════════════════════════════════════
async function handleFormSubmit(e) {
  e.preventDefault();

  const birthDateEl = document.getElementById('birth_date');
  const locInput = document.getElementById('location_query');
  const birthTimeEl = document.getElementById('birth_time');
  const approxStartEl = document.getElementById('approx_start');
  const approxEndEl = document.getElementById('approx_end');

  [birthDateEl, locInput, birthTimeEl, approxStartEl, approxEndEl].forEach(el =>
    el?.classList.remove('is-invalid')
  );

  const birthDate = birthDateEl.value;
  if (!birthDate) {
    birthDateEl.classList.add('is-invalid');
    showError('Please enter your date of birth.');
    return;
  }

  // Auto-geocode if user typed a birthplace and clicked Calculate directly
  let lat = document.getElementById('lat').value;
  let lon = document.getElementById('lon').value;
  if ((!lat || !lon) && locInput.value.trim()) {
    clearTimeout(geocodeDebounce);
    const geo = await geocodeLocation(locInput.value);
    if (geo) {
      lat = document.getElementById('lat').value;
      lon = document.getElementById('lon').value;
    }
  }

  if (!lat || !lon) {
    locInput.classList.add('is-invalid');
    showError('Please search for a birthplace, pick a quick city, or enter coordinates manually.');
    return;
  }

  const mode = document.getElementById('birth_time_mode').value;
  if (mode === 'exact' && !birthTimeEl.value) {
    birthTimeEl.classList.add('is-invalid');
    showError('Please enter your exact birth time, or switch to Approximate/Unknown.');
    return;
  }
  if (mode === 'approximate') {
    if (!approxStartEl.value || !approxEndEl.value) {
      approxStartEl.classList.add('is-invalid');
      approxEndEl.classList.add('is-invalid');
      showError('Please select a period or enter start and end times.');
      return;
    }
    if (approxEndEl.value <= approxStartEl.value) {
      approxEndEl.classList.add('is-invalid');
      showError('Approximate end time must be later than start time.');
      return;
    }
  }

  const startYear = parseInt(document.getElementById('start_year').value, 10);
  const endYear = parseInt(document.getElementById('end_year').value, 10);
  if (isNaN(startYear) || isNaN(endYear) || endYear < startYear) {
    showError('Please enter a valid year range (From year <= To year).');
    return;
  }
  if (endYear - startYear > 120) {
    showError('Year range cannot exceed 120 years per calculation.');
    return;
  }

  const payload = {
    birth_date: birthDate,
    lat: parseFloat(lat),
    lon: parseFloat(lon),
    timezone: document.getElementById('timezone').value,
    location_name: document.getElementById('location_name').value,
    ayanamsha: document.getElementById('ayanamsha').value,
    lunar_system: document.getElementById('lunar_system').value,
    observance_method: document.getElementById('observance_method').value,
    adhika_rule: document.getElementById('adhika_rule').value,
    start_year: startYear,
    end_year: endYear,
    birth_time_mode: mode,
  };

  if (mode === 'exact') {
    payload.birth_time = birthTimeEl.value;
  } else if (mode === 'approximate') {
    payload.birth_time_start = approxStartEl.value;
    payload.birth_time_end = approxEndEl.value;
  }

  const btnCalc = document.getElementById('btn-calculate');
  if (btnCalc) btnCalc.disabled = true;
  showLoading(true);
  animateLoadingSteps();

  try {
    const resp = await fetch('/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) {
      showError(data.error || 'Calculation failed.');
      return;
    }
    selectedCandidateIdx = 0;
    lastResult = { ...data, _payload: payload };
    renderResults(lastResult);
    const resSection = document.getElementById('results-section');
    resSection.style.display = '';
    resSection.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    showError('A network error occurred. Please try again.');
  } finally {
    showLoading(false);
    if (btnCalc) btnCalc.disabled = false;
  }
}

function showLoading(show) {
  document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
  if (!show) {
    loadingTimers.forEach(clearTimeout);
    loadingTimers = [];
  }
}

function animateLoadingSteps() {
  loadingTimers.forEach(clearTimeout);
  loadingTimers = [];
  const steps = ['ps-1', 'ps-2', 'ps-3', 'ps-4'];
  steps.forEach(id => document.getElementById(id)?.classList.remove('active'));
  steps.forEach((id, i) => {
    const tid = setTimeout(() => {
      document.getElementById(id)?.classList.add('active');
    }, i * 500);
    loadingTimers.push(tid);
  });
}

function showError(msg) {
  const alert = document.createElement('div');
  alert.className = 'alert alert-danger alert-dismissible fade show position-fixed bottom-0 end-0 m-3 shadow';
  alert.style.zIndex = '10000';
  alert.innerHTML = `<i class="fas fa-exclamation-circle me-2"></i><span>${escapeHtml(msg)}</span>
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
  document.body.appendChild(alert);
  setTimeout(() => alert.remove(), 6500);
}
window.showError = showError;

function renderCloudSaveBarHtml() {
  if (!window.TithiAuth || !window.TithiAuth.isConfigured()) return '';
  if (window.TithiAuth.isAuthenticated()) {
    return `
      <div class="cloud-save-bar p-3 mb-4 rounded d-flex flex-wrap align-items-center justify-content-between gap-2">
        <div class="small fw-semibold text-navy">
          <i class="fas fa-cloud-upload-alt text-saffron me-2"></i>${escapeHtml(t('cloudSavePrompt'))}
        </div>
        <div class="d-flex flex-wrap gap-2">
          <button type="button" class="btn btn-sm btn-saffron" id="btn-save-profile"
                  onclick="window.TithiAuth.openSaveProfileModal()">
            <i class="fas fa-bookmark me-1"></i>${escapeHtml(t('saveProfileBtn'))}
          </button>
          <button type="button" class="btn btn-sm btn-outline-primary" id="btn-save-history"
                  onclick="window.TithiAuth.saveCalculationHistory()">
            <i class="fas fa-history me-1"></i>${escapeHtml(t('saveHistoryBtn'))}
          </button>
        </div>
      </div>`;
  }
  return `
    <div class="cloud-save-bar p-3 mb-4 rounded d-flex flex-wrap align-items-center justify-content-between gap-2">
      <div class="small text-muted">
        <i class="fas fa-lock text-saffron me-2"></i>${escapeHtml(t('loginToSavePrompt'))}
      </div>
      <button type="button" class="btn btn-sm btn-outline-secondary"
              onclick="window.TithiAuth.openAuthModal('login')">
        <i class="fas fa-sign-in-alt me-1"></i>${escapeHtml(t('loginToSaveBtn'))}
      </button>
    </div>`;
}

function refreshCloudSaveBar() {
  const host = document.getElementById('cloud-save-bar-host');
  if (host) {
    host.innerHTML = renderCloudSaveBarHtml();
  }
}

// ══════════════════════════════════════════════════════
// Results Rendering
// ══════════════════════════════════════════════════════
function statusSlug(status) {
  return String(status || 'unknown').toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

function selectCandidate(idx) {
  selectedCandidateIdx = idx;
  if (lastResult) renderResults(lastResult);
}

function renderResults(data) {
  const container = document.getElementById('results-container');
  const p = data.panchang;
  const calendars = (data.candidate_calendars && data.candidate_calendars.length)
    ? data.candidate_calendars
    : [{
        tithi: p.tithis[0],
        lunar_month: p.lunar_month,
        entries: data.birthday_entries || [],
        next_birthday: data.next_birthday,
      }];

  if (selectedCandidateIdx >= calendars.length) selectedCandidateIdx = 0;
  const activeCal = calendars[selectedCandidateIdx];
  const entries = activeCal.entries || [];
  const nb = activeCal.next_birthday || data.next_birthday;

  let html = '';

  // Hero
  html += `
  <div class="results-hero">
    <div class="container">
      <div class="results-title">🕉 ${escapeHtml(t('resultsHeroTitle'))}</div>
      <div class="results-subtitle">${escapeHtml(p.birth_date_display)} · ${escapeHtml(p.location_name)}</div>
    </div>
  </div>
  <div class="container py-4">
  <div id="cloud-save-bar-host">${renderCloudSaveBarHtml()}</div>`;

  // Ambiguity alert
  if (p.ambiguity_message) {
    html += `
    <div class="ambiguity-alert">
      <i class="fas fa-exclamation-triangle text-warning me-2"></i>
      <strong>${escapeHtml(t('noticePrefix'))}</strong> ${escapeHtml(p.ambiguity_message)}
    </div>`;
  }

  // Next birthday countdown
  if (nb && nb.date) {
    const dateObj = new Date(nb.date + 'T00:00:00');
    const dateStr = dateObj.toLocaleDateString(currentLang === 'hi' ? 'hi-IN' : 'en-IN', {
      day: 'numeric', month: 'long', year: 'numeric',
    });
    const days = nb.days_until;
    const isToday = days === 0;
    html += `
    <div class="next-birthday-banner mb-4">
      <div class="next-birthday-label">${isToday ? '🎉 ' + escapeHtml(t('todayBirthday')) : '⏰ ' + escapeHtml(t('nextBirthday'))}</div>
      <div class="next-birthday-countdown">${escapeHtml(dateStr)}</div>
      ${!isToday ? `<div class="next-birthday-label mt-1"><strong>${days}</strong> ${escapeHtml(t('daysFromToday'))}</div>` : ''}
    </div>`;
  }

  // Birth Info + Panchang Card
  const birthTimeDisplay = p.birth_time_local ? p.birth_time_local : t('unknownTime');
  const conventionsText = `${p.lunar_system.charAt(0).toUpperCase() + p.lunar_system.slice(1)} · ${p.observance_label}`;

  html += `
  <div class="panchang-card">
    <div class="card-header">
      <i class="fas fa-scroll"></i> ${escapeHtml(t('birthInfoHeader'))}
    </div>
    <div class="card-body">
      <div class="row g-3 mb-4">
        <div class="col-md-4 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">${escapeHtml(t('dob'))}</div>
            <div class="panchang-value">${escapeHtml(p.birth_date_display)}</div>
          </div>
        </div>
        <div class="col-md-4 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">${escapeHtml(t('birthTime'))}</div>
            <div class="panchang-value" style="font-size:0.95rem">${escapeHtml(birthTimeDisplay)}</div>
          </div>
        </div>
        <div class="col-md-4 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">${escapeHtml(t('birthplace'))}</div>
            <div class="panchang-value" style="font-size:0.9rem">${escapeHtml(p.location_name)}</div>
          </div>
        </div>
        <div class="col-md-3 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">${escapeHtml(t('coords'))}</div>
            <div class="panchang-value" style="font-size:0.9rem">${p.lat.toFixed(4)}°, ${p.lon.toFixed(4)}°</div>
          </div>
        </div>
        <div class="col-md-3 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">${escapeHtml(t('timezone'))}</div>
            <div class="panchang-value" style="font-size:0.9rem">${escapeHtml(p.timezone_str)}</div>
          </div>
        </div>
        <div class="col-md-3 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">🌅 ${escapeHtml(t('sunrise'))}</div>
            <div class="panchang-value" style="font-size:0.95rem">${escapeHtml(p.sunrise_local || 'N/A')}</div>
          </div>
        </div>
        <div class="col-md-3 col-sm-6">
          <div class="panchang-item">
            <div class="panchang-label">🌇 ${escapeHtml(t('sunset'))}</div>
            <div class="panchang-value" style="font-size:0.95rem">${escapeHtml(p.sunset_local || 'N/A')}</div>
          </div>
        </div>
      </div>

      <h6 class="text-muted text-uppercase small fw-bold mb-3">${escapeHtml(t('panchangElements'))}</h6>
      <div class="panchang-grid">`;

  p.tithis.forEach((tObj, i) => {
    const startDisp = tObj.start_local || tObj.start_utc || '';
    const endDisp = tObj.end_local || tObj.end_utc || '';
    const primaryTithi = currentLang === 'hi' ? `${tObj.paksha_hi} ${tObj.name_hi}` : `${tObj.paksha_en} ${tObj.name_en}`;
    const secondaryTithi = currentLang === 'hi' ? `${tObj.paksha_en} ${tObj.name_en}` : `${tObj.paksha_hi} ${tObj.name_hi}`;
    html += `
      <div class="panchang-item" style="border-left-color: ${i === 0 ? '#FF8C00' : '#6C757D'}">
        <div class="panchang-label">🌙 ${escapeHtml(t('tithi'))} ${p.tithis.length > 1 ? `(${escapeHtml(t('optionLabel'))} ${i + 1})` : ''}</div>
        <div class="panchang-value">${escapeHtml(primaryTithi)}</div>
        <div class="panchang-value-hi">${escapeHtml(secondaryTithi)}</div>
        <div class="mt-1" style="font-size:0.75rem; color:var(--muted)">
          ${startDisp ? 'Start: ' + escapeHtml(startDisp) : ''}${endDisp ? '<br>End: ' + escapeHtml(endDisp) : ''}
        </div>
      </div>`;
  });

  if (p.tithi_at_sunrise) {
    const srPrimary = currentLang === 'hi'
      ? `${p.tithi_at_sunrise.paksha_hi} ${p.tithi_at_sunrise.name_hi}`
      : `${p.tithi_at_sunrise.paksha_en} ${p.tithi_at_sunrise.name_en}`;
    html += `
      <div class="panchang-item" style="border-left-color:#1B2A4A">
        <div class="panchang-label">🌅 ${escapeHtml(t('tithiAtSunrise'))}</div>
        <div class="panchang-value">${escapeHtml(srPrimary)}</div>
        <div class="panchang-value-hi">${escapeHtml(p.tithi_at_sunrise.name_hi)}</div>
        <small class="text-muted">${escapeHtml(t('sunriseRef'))}</small>
      </div>`;
  }

  if (p.lunar_month) {
    const lmPrimary = currentLang === 'hi' ? p.lunar_month.name_hi : p.lunar_month.name_en;
    html += `
      <div class="panchang-item">
        <div class="panchang-label">📅 ${escapeHtml(t('lunarMonth'))}</div>
        <div class="panchang-value">${escapeHtml(lmPrimary)}${p.lunar_month.is_adhika ? ' (Adhika)' : ''}</div>
        <div class="panchang-value-hi">${escapeHtml(p.lunar_month.name_hi)} · ${escapeHtml(p.lunar_system.toUpperCase())}</div>
        <small class="text-muted">Solar sign: ${escapeHtml(p.lunar_month.solar_sign_en)}</small>
      </div>`;
  }

  if (p.nakshatra) {
    const nkPrimary = currentLang === 'hi' ? p.nakshatra.name_hi : p.nakshatra.name_en;
    html += `
      <div class="panchang-item">
        <div class="panchang-label">⭐ ${escapeHtml(t('nakshatra'))}</div>
        <div class="panchang-value">${escapeHtml(nkPrimary)} (Pada ${p.nakshatra.pada})</div>
        <div class="panchang-value-hi">${escapeHtml(p.nakshatra.name_hi)}</div>
        <small class="text-muted">Lord: ${escapeHtml(p.nakshatra.lord)}</small>
      </div>`;
  }

  if (p.yoga) {
    html += `
      <div class="panchang-item">
        <div class="panchang-label">🔮 ${escapeHtml(t('yoga'))}</div>
        <div class="panchang-value">${escapeHtml(currentLang === 'hi' ? p.yoga.name_hi : p.yoga.name_en)}</div>
        <div class="panchang-value-hi">${escapeHtml(p.yoga.name_hi)}</div>
      </div>`;
  }

  if (p.karana) {
    html += `
      <div class="panchang-item">
        <div class="panchang-label">⚡ ${escapeHtml(t('karana'))}</div>
        <div class="panchang-value">${escapeHtml(currentLang === 'hi' ? p.karana.name_hi : p.karana.name_en)}</div>
        <div class="panchang-value-hi">${escapeHtml(p.karana.name_hi)}</div>
      </div>`;
  }

  html += `
      </div><!-- /.panchang-grid -->
      <div class="mt-3 p-2 rounded" style="background:rgba(0,0,0,0.03); font-size:0.8rem; color:var(--muted)">
        <i class="fas fa-info-circle me-1"></i>
        ${escapeHtml(t('ayanamsha'))}: <strong>${escapeHtml(p.ayanamsha_name)}</strong> ·
        ${escapeHtml(t('conventions'))}: <strong>${escapeHtml(conventionsText)}</strong> ·
        Confidence: <strong>${escapeHtml(p.confidence)}</strong>
      </div>
    </div>
  </div>`;

  // Candidate switcher if multiple Tithis
  if (calendars.length > 1) {
    html += `<div class="mb-3">
      <div class="fw-semibold small text-muted mb-2">${escapeHtml(t('candidatePrompt'))}</div>
      <div class="candidate-tabs">`;
    calendars.forEach((cal, idx) => {
      const lbl = currentLang === 'hi'
        ? `${t('optionLabel')} ${idx + 1}: ${cal.lunar_month.name_hi} ${cal.tithi.paksha_hi} ${cal.tithi.name_hi}`
        : `${t('optionLabel')} ${idx + 1}: ${cal.lunar_month.name_en} ${cal.tithi.paksha_en} ${cal.tithi.name_en}`;
      html += `<button type="button" class="candidate-tab-btn ${idx === selectedCandidateIdx ? 'active' : ''}" onclick="selectCandidate(${idx})">${escapeHtml(lbl)}</button>`;
    });
    html += `</div></div>`;
  }

  // Birthday Calendar Card (Visual Grid + Export + Table)
  const activeMonthLabel = activeCal.lunar_month
    ? (currentLang === 'hi' ? activeCal.lunar_month.name_hi : activeCal.lunar_month.name_en)
    : '';
  const activeTithiLabel = activeCal.tithi
    ? (currentLang === 'hi' ? `${activeCal.tithi.paksha_hi} ${activeCal.tithi.name_hi}` : `${activeCal.tithi.paksha_en} ${activeCal.tithi.name_en}`)
    : '';

  html += `
  <div class="panchang-card">
    <div class="card-header">
      <i class="fas fa-calendar-alt"></i>
      ${escapeHtml(t('calendarHeader'))} (${data.start_year}–${data.end_year}) — ${escapeHtml(activeMonthLabel)} ${escapeHtml(activeTithiLabel)}
    </div>
    <div class="card-body p-0">
      <div class="p-3 border-bottom">
        <div class="export-toolbar">
          <button class="btn btn-export" type="button" onclick="exportData('csv')">
            <i class="fas fa-file-csv me-1"></i>${escapeHtml(t('dlCsv'))}
          </button>
          <button class="btn btn-export" type="button" onclick="exportData('excel')">
            <i class="fas fa-file-excel me-1"></i>${escapeHtml(t('dlExcel'))}
          </button>
          <button class="btn btn-export" type="button" onclick="exportData('pdf')">
            <i class="fas fa-file-pdf me-1"></i>${escapeHtml(t('dlPdf'))}
          </button>
          <button class="btn btn-export" type="button" onclick="exportData('ics')">
            <i class="fas fa-calendar-plus me-1"></i>${escapeHtml(t('dlIcs'))}
          </button>
          <button class="btn btn-export" type="button" onclick="window.print()">
            <i class="fas fa-print me-1"></i>${escapeHtml(t('printBtn'))}
          </button>
        </div>
      </div>

      <!-- Visual Year-by-Year Calendar Grid -->
      <div class="px-3 pt-3 pb-1 small fw-bold text-uppercase text-muted">${escapeHtml(t('visualTitle'))}</div>
      <div class="year-visual-grid">`;

  const todayIso = data.today_iso || new Date().toISOString().split('T')[0];
  const currentYearNum = parseInt(todayIso.slice(0, 4), 10);

  entries.forEach(entry => {
    let tileClass = 'upcoming';
    if (entry.year === currentYearNum || entry.is_today) tileClass = 'current';
    else if (entry.gregorian_date && entry.gregorian_date < todayIso) tileClass = 'past';
    if (entry.status === 'Kshaya') tileClass += ' kshaya';
    else if (entry.status === 'Vriddhi') tileClass += ' vriddhi';

    const shortDate = entry.gregorian_date
      ? new Date(entry.gregorian_date + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
      : '—';
    const dayDisp = currentLang === 'hi' ? (entry.weekday_hi || entry.weekday || '') : (entry.weekday || '');

    html += `
        <div class="year-tile ${tileClass}">
          <div class="yt-year">${entry.year}</div>
          <div class="yt-date fw-semibold">${escapeHtml(shortDate)}</div>
          <div class="yt-day">${escapeHtml(dayDisp)}</div>
          <span class="status-badge status-${statusSlug(entry.status)} mt-1">${escapeHtml(entry.status)}</span>
        </div>`;
  });

  html += `
      </div>

      <div class="birthday-table-wrapper">
        <table class="birthday-table">
          <thead>
            <tr>
              <th>${escapeHtml(t('colYear'))}</th>
              <th>${escapeHtml(t('colDate'))}</th>
              <th>${escapeHtml(t('colDay'))}</th>
              <th>${escapeHtml(t('colMonth'))}</th>
              <th>${escapeHtml(t('colTithi'))}</th>
              <th>${escapeHtml(t('colStart'))}</th>
              <th>${escapeHtml(t('colEnd'))}</th>
              <th>${escapeHtml(t('colStatus'))}</th>
              <th>${escapeHtml(t('colNotes'))}</th>
            </tr>
          </thead>
          <tbody>`;

  entries.forEach(entry => {
    let rowClass = '';
    if (entry.is_today) rowClass = 'row-today';
    else if (entry.gregorian_date && entry.gregorian_date < todayIso) rowClass = 'row-past';

    const startDisp = entry.tithi_start_local || entry.tithi_start_utc || '—';
    const endDisp = entry.tithi_end_local || entry.tithi_end_utc || '—';
    const weekdayDisp = currentLang === 'hi' ? (entry.weekday_hi || entry.weekday || '') : (entry.weekday || '');

    html += `
            <tr class="${rowClass}">
              <td><strong>${entry.year}</strong></td>
              <td>
                ${entry.gregorian_date_display ? escapeHtml(entry.gregorian_date_display) : '<span class="text-muted">N/A</span>'}
                ${entry.is_today ? ' <span class="badge bg-warning text-dark">Today!</span>' : ''}
              </td>
              <td>${escapeHtml(weekdayDisp)}</td>
              <td>${escapeHtml(entry.lunar_month_en || '')}</td>
              <td>
                ${escapeHtml(entry.tithi_name_en)}
                <div class="panchang-value-hi" style="font-size:0.78rem">${escapeHtml(entry.tithi_name_hi)}</div>
              </td>
              <td style="font-size:0.82rem">${escapeHtml(startDisp)}</td>
              <td style="font-size:0.82rem">${escapeHtml(endDisp)}</td>
              <td><span class="status-badge status-${statusSlug(entry.status)}">${escapeHtml(entry.status)}</span></td>
              <td style="font-size:0.78rem; max-width:240px">
                ${escapeHtml(entry.notes || '')}
                ${entry.alternate_dates && entry.alternate_dates.length
                  ? '<br><small class="text-warning fw-semibold">Alternate: ' + escapeHtml(entry.alternate_dates.join(', ')) + '</small>'
                  : ''}
              </td>
            </tr>`;
  });

  html += `
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="text-center py-3 recalc-actions">
    <button type="button" class="btn btn-outline-secondary" onclick="document.getElementById('calculator').scrollIntoView({behavior:'smooth'})">
      <i class="fas fa-redo me-2"></i>${escapeHtml(t('recalcBtn'))}
    </button>
  </div>
  </div>`;

  container.innerHTML = html;
}

// ══════════════════════════════════════════════════════
// Export & External Integration Hooks
// ══════════════════════════════════════════════════════
async function exportData(type) {
  if (!lastResult) {
    showError('Please calculate first.');
    return;
  }
  if (!lastResult._payload) {
    showError('Export unavailable: historical calculation input data could not be validated. Please recalculate.');
    return;
  }
  try {
    const resp = await fetch('/export/' + type, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastResult._payload),
    });
    if (!resp.ok) {
      let errMsg = 'Export failed';
      try {
        const errData = await resp.json();
        if (errData.error) errMsg = errData.error;
      } catch (_) {}
      throw new Error(errMsg);
    }
    const blob = await resp.blob();
    const extMap = { csv: '.csv', excel: '.xlsx', pdf: '.pdf', ics: '.ics' };
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'hindu_birthday' + (extMap[type] || '.bin');
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    showError('Export failed: ' + err.message);
  }
}

function fillCalculatorForm(inp) {
  if (!inp) return;
  const setVal = (id, v) => {
    const el = document.getElementById(id);
    if (el && v !== undefined && v !== null) el.value = v;
  };
  setVal('birth_date', inp.birth_date || '');
  setVal('location_query', inp.location_name || '');
  if (inp.lat !== undefined && inp.lon !== undefined) {
    setLocation({
      lat: inp.lat,
      lon: inp.lon,
      timezone: inp.timezone || 'UTC',
      display_name: inp.location_name || `${inp.lat}, ${inp.lon}`,
    });
    const status = document.getElementById('geocode-status');
    if (status) {
      status.innerHTML = `<span class="geocode-success"><i class="fas fa-check-circle me-1"></i>${escapeHtml(inp.location_name || '')}</span>`;
    }
  }
  const mode = inp.birth_time_mode || 'unknown';
  switchTimeMode(mode);
  if (mode === 'exact') setVal('birth_time', inp.birth_time || '');
  if (mode === 'approximate') {
    setVal('approx_start', inp.birth_time_start || '');
    setVal('approx_end', inp.birth_time_end || '');
  }
  setVal('ayanamsha', inp.ayanamsha || 'lahiri');
  setVal('lunar_system', inp.lunar_system || 'amanta');
  setVal('observance_method', inp.observance_method || 'sunrise');
  setVal('adhika_rule', inp.adhika_rule || 'nija');
  if (inp.start_year) setVal('start_year', inp.start_year);
  if (inp.end_year) setVal('end_year', inp.end_year);
  updateConventionExplanation();
}

async function runCalculationFromForm() {
  const form = document.getElementById('mainForm');
  if (form) {
    await handleFormSubmit({ preventDefault: () => {} });
  }
}

function displaySavedCalculation(resultData, validInputPayload) {
  selectedCandidateIdx = 0;
  lastResult = { ...resultData, _payload: validInputPayload || null };
  renderResults(lastResult);
  const resSection = document.getElementById('results-section');
  if (resSection) {
    resSection.style.display = '';
    resSection.scrollIntoView({ behavior: 'smooth' });
  }
}

window.TithiCalculator = {
  fillCalculatorForm,
  runCalculationFromForm,
  displaySavedCalculation,
  getLastCalculation: () => lastResult,
  setActiveSavedProfileId: (id) => { activeSavedProfileId = id; },
  getActiveSavedProfileId: () => activeSavedProfileId,
  refreshCloudSaveBar,
};
