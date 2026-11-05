/* Time audit mini app. No build step. See SPEC section 13 for the API shapes. */
(function () {
  'use strict';

  var qs = new URLSearchParams(location.search);
  var MOCK = qs.get('mock') === '1';
  var DEV_USER = qs.get('dev_user');
  var tg = (window.Telegram && window.Telegram.WebApp) || null;
  var inTG = !!(tg && tg.initData);

  var state = { me: null, cats: {}, tab: 'today', date: null, cache: {}, loadedAt: 0, tokens: {} };
  var charts = {};
  var $ = function (s, r) { return (r || document).querySelector(s); };

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function dur(min) {
    min = Math.max(0, Math.round(min || 0));
    if (min < 60) return min + 'm';
    return Math.floor(min / 60) + 'h ' + pad(min % 60) + 'm';
  }
  function durLimit(min) { // 15m, 1h, 1h 30m
    if (min < 60) return min + 'm';
    return Math.floor(min / 60) + 'h' + (min % 60 ? ' ' + (min % 60) + 'm' : '');
  }
  function hhmm(m) { return pad(Math.floor(m / 60) % 24) + ':' + pad(m % 60); }
  function addDays(s, n) {
    var p = s.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)).toISOString().slice(0, 10);
  }
  function dateLabel(s) {
    var today = state.me.user.today;
    if (s === today) return 'Today';
    if (s === addDays(today, -1)) return 'Yesterday';
    var p = s.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2])).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
  }
  function cat(id) { return state.cats[id] || { id: id, name: 'Unknown', emoji: '•', is_waste: false, color: '#8A94A6' }; }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function haptic(kind) {
    try {
      var h = tg && tg.HapticFeedback; if (!h) return;
      if (kind === 'success' || kind === 'error' || kind === 'warning') h.notificationOccurred(kind);
      else if (kind === 'select') h.selectionChanged();
      else h.impactOccurred('light');
    } catch (e) { /* ignore */ }
  }
  var toastTimer;
  function toast(msg) {
    var t = $('#toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2200);
  }
  function confirmDlg(msg) {
    return new Promise(function (resolve) {
      try {
        if (inTG && tg.showConfirm && (!tg.isVersionAtLeast || tg.isVersionAtLeast('6.2'))) {
          tg.showConfirm(msg, function (ok) { resolve(!!ok); });
          return;
        }
      } catch (e) { /* fall through */ }
      resolve(window.confirm(msg));
    });
  }

  /* ---------- theme ---------- */
  function applyTheme() {
    var root = document.documentElement, forced = qs.get('theme');
    if ((MOCK || DEV_USER) && (forced === 'dark' || forced === 'light')) root.setAttribute('data-theme', forced);
    else if (inTG && (tg.colorScheme === 'dark' || tg.colorScheme === 'light')) root.setAttribute('data-theme', tg.colorScheme);
  }

  /* ---------- api ---------- */
  function api(method, path, body) {
    if (MOCK) return window.MockAPI.handle(method, path, body);
    var headers = { Accept: 'application/json' };
    if (DEV_USER) headers['X-Dev-User'] = DEV_USER;
    else headers['X-Telegram-Init-Data'] = (tg && tg.initData) || '';
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(path, { method: method, headers: headers, body: body !== undefined ? JSON.stringify(body) : undefined })
      .catch(function () { throw { code: 'network', message: 'Network error' }; })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (data) {
          if (!res.ok) {
            throw { code: (data && data.error) || 'http_' + res.status, status: res.status,
                    message: (data && data.message) || 'Something went wrong.' };
          }
          return data;
        });
      });
  }
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script'); s.src = src; s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
    });
  }

  /* ---------- screens: skeleton / error ---------- */
  function sk(h, extra) { return '<div class="sk" style="height:' + h + 'px;' + (extra || '') + '"></div>'; }
  function skeleton(kind) {
    if (kind === 'today') return sk(40, 'margin-bottom:12px') + sk(420, 'margin-bottom:12px;border-radius:4px') +
      sk(100, 'margin-bottom:12px;border-radius:16px') + sk(180, 'border-radius:16px');
    if (kind === 'week') return sk(64, 'margin-bottom:12px;border-radius:16px') + sk(400, 'margin-bottom:12px;border-radius:4px') +
      sk(250, 'margin-bottom:12px;border-radius:16px') + sk(170, 'border-radius:16px');
    return sk(120, 'margin-bottom:12px;border-radius:16px') + sk(120, 'margin-bottom:12px;border-radius:16px') + sk(200, 'border-radius:16px');
  }
  function showError(view, err, retry) {
    var el = $('#view-' + view);
    el.innerHTML = '<div class="card state"><h1>Couldn’t load</h1><p>' +
      (err && err.code === 'network' ? 'Check your connection and try again.' : esc((err && err.message) || 'Something went wrong.')) +
      '</p><button class="btn" data-act="retry">Try again</button></div>';
    el._retry = retry;
  }
  function handleFatal(err) {
    if (err && (err.code === 'not_registered' || err.status === 404)) {
      $('#app').innerHTML = '<div class="state fatal"><h1>One quick step first</h1><p>Open the bot and press /start first. Once your audit is set up, your dashboard shows up here.</p>' +
        (inTG ? '<button class="btn" data-act="close">Close</button>' : '') + '</div>';
      return true;
    }
    if (err && (err.status === 401 || err.status === 403)) {
      $('#app').innerHTML = '<div class="state fatal"><h1>Open from Telegram</h1><p>This dashboard works inside the Telegram bot. Open it from the bot menu.</p></div>';
      return true;
    }
    return false;
  }


  /* ---------- receipt ---------- */
  var MON = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  var DOW = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
  function rcDate(s, withDow) {
    var p = s.split('-').map(Number), dt = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
    return (withDow ? DOW[dt.getUTCDay()] + ' ' : '') + pad(p[2]) + ' ' + MON[p[1] - 1] + (withDow ? ' ' + p[0] : '');
  }
  function daysBetween(a, b) { return Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / 864e5); }
  function perYear(min) { return Math.round(min * 365 / 1440); }
  function rrow(l, r, cls, rid) {
    return '<div class="rc-row' + (cls ? ' ' + cls : '') + '"><span class="l">' + l + '</span><span class="r"' + (rid ? ' id="' + rid + '"' : '') + '>' + r + '</span></div>';
  }
  var RC_RULE = '<div class="rc-rule" aria-hidden="true"></div>';
  var RC_DOUBLE = '<div class="rc-rule dbl" aria-hidden="true"></div>';
  function receiptWrap(label, inner) {
    return '<div class="receipt-wrap"><article class="receipt" aria-label="' + esc(label) + '">' + inner +
      '<div class="rc-barcode" aria-hidden="true"></div></article></div>';
  }
  function itemLine(c, minutes, qty) {
    return rrow((qty != null ? '<span class="q">' + pad(qty) + '</span>' : '') + '<span class="n">' + esc(c.name) + '</span>' +
      (c.is_waste ? '<b class="star" aria-label="waste">*</b>' : ''), dur(minutes), 'item');
  }
  function todayReceipt(d) {
    var u = state.me.user, isToday = state.date === u.today;
    var dayN = u.challenge_day - daysBetween(state.date, u.today);
    var meta = rcDate(state.date, true);
    var head = '<div class="rc-brand">SPENT · YOUR DAY, ITEMIZED</div>' +
      rrow(esc(meta), dayN >= 1 && dayN <= u.challenge_days ? 'DAY ' + dayN + '/' + u.challenge_days : '', 'meta') + RC_RULE;
    var foot = '<div class="rc-foot">* = WHAT YOU CALL WASTE</div>';
    if (!(d.tracked_minutes > 0)) {
      return receiptWrap('Receipt for ' + dateLabel(state.date), head +
        '<div class="rc-empty"><b>NOTHING ITEMIZED YET</b><span>' + (isToday ? 'TRACK SOMETHING AND IT SHOWS UP HERE.' : 'NO ENTRIES ON THIS DAY.') + '</span></div>' + RC_RULE + foot);
    }
    var qty = {};
    d.entries.forEach(function (e) { if (e.end_min != null && !(d.running && e.id === d.running.entry_id)) qty[e.category_id] = (qty[e.category_id] || 0) + 1; });
    if (d.running) qty[d.running.category_id] = (qty[d.running.category_id] || 0) + 1;
    var rows = d.totals.slice().sort(function (a, b) { return b.minutes - a.minutes; }).filter(function (t) { return t.minutes > 0; });
    var h = head + rrow('QTY&nbsp;&nbsp;ITEM', 'TIME', 'cols');
    rows.forEach(function (t) { h += itemLine(cat(t.category_id), t.minutes, qty[t.category_id] || 1); });
    if (d.running) h += rrow('▸ ' + esc(cat(d.running.category_id).name) + ' (running)', dur(d.running.minutes), 'run', 'run-min');
    h += RC_RULE + rrow('TRACKED', dur(d.tracked_minutes)) + rrow('NOT TRACKED', dur(d.untracked_minutes), 'muted') + RC_DOUBLE;
    h += totalBlock(d.waste_minutes, Math.round(d.waste_share * 100) + '% OF TRACKED', 'CLEAN DAY. SUSPICIOUS.');
    if (d.waste_minutes > 0) h += RC_RULE + '<div class="rc-year">IF EVERY DAY WAS LIKE ' + (isToday ? 'TODAY' : 'THAT ONE') + ':<b>' + perYear(d.waste_minutes) + ' DAYS A YEAR</b></div>';
    return receiptWrap('Receipt for ' + dateLabel(state.date), h + RC_RULE + foot);
  }
  function totalBlock(min, pct, clean) {
    return '<div class="rc-total"><div class="lab">TOTAL WASTED' + (min > 0 ? ' <b class="star">*</b>' : '') + '</div><div class="big">' + dur(min) + '</div>' +
      '<div class="pct">' + (min > 0 ? pct : clean) + '</div></div>';
  }
  function weekReceipt(w, perDay, daysN) {
    var head = '<div class="rc-brand">SPENT · YOUR WEEK, ITEMIZED</div>' + rrow(rcDate(w.start) + ' – ' + rcDate(w.end) + ' ' + w.end.slice(0, 4), '', 'meta') + RC_RULE;
    var foot = '<div class="rc-foot">* = WHAT YOU CALL WASTE</div>';
    if (!(w.tracked_minutes > 0)) {
      return receiptWrap('Weekly receipt', head + '<div class="rc-empty"><b>NOTHING ITEMIZED YET</b><span>TRACK A FEW DAYS AND THE WEEK ADDS UP HERE.</span></div>' + RC_RULE + foot);
    }
    var tots = w.totals.slice().sort(function (a, b) { return b.minutes - a.minutes; }).filter(function (t) { return t.minutes > 0; });
    var h = head + rrow('ITEM', 'TIME', 'cols');
    tots.slice(0, 6).forEach(function (t) { h += itemLine(cat(t.category_id), t.minutes); });
    if (tots.length > 6) h += rrow('+' + (tots.length - 6) + ' MORE', dur(tots.slice(6).reduce(function (a, t) { return a + t.minutes; }, 0)), 'muted');
    h += RC_RULE + rrow('TRACKED', dur(w.tracked_minutes)) + rrow('NOT TRACKED', dur(w.untracked_minutes), 'muted') + RC_DOUBLE;
    h += totalBlock(w.waste_minutes, Math.round(w.waste_share * 100) + '% OF TRACKED', 'CLEAN WEEK. SUSPICIOUS.');
    if (w.waste_minutes > 0) {
      h += rrow('≈ ' + dur(perDay) + ' A DAY', '', 'sum');
      h += RC_RULE + '<div class="rc-year">AT THIS PACE:<b>' + perYear(perDay) + ' DAYS A YEAR</b></div>';
    }
    if (w.prev_waste_minutes != null) {
      var diff = w.waste_minutes - w.prev_waste_minutes;
      h += RC_RULE + rrow('VS LAST WEEK', Math.abs(diff) < 5 ? 'SAME' : (diff < 0 ? '−' : '+') + dur(Math.abs(diff)), 'delta' + (diff >= 5 ? ' up' : ''));
    }
    return receiptWrap('Weekly receipt', h + RC_RULE + foot);
  }

  /* ---------- Today ---------- */
  function loadToday() {
    var tok = state.tokens.today = (state.tokens.today || 0) + 1;
    var el = $('#view-today');
    el.innerHTML = skeleton('today');
    return api('GET', '/api/day?date=' + state.date).then(function (d) {
      if (tok !== state.tokens.today) return;
      state.cache.day = d; state.loadedAt = Date.now(); renderToday();
    }).catch(function (e) {
      if (tok !== state.tokens.today) return;
      if (!handleFatal(e)) showError('today', e, loadToday);
    });
  }
  function nowMinOf(d) {
    return d.date === state.me.user.today ? Math.min(d.awake_end_min, d.awake_start_min + d.awake_minutes) : null;
  }
  function timelineHTML(d) {
    var s = d.awake_start_min, e = d.awake_end_min, len = e - s, now = nowMinOf(d);
    var pct = function (x) { return (Math.min(Math.max(x, s), e) - s) / len * 100; };
    var segs = '';
    d.entries.forEach(function (en) {
      if (en.end_min == null || (d.running && en.id === d.running.entry_id)) return;
      var l = pct(en.start_min), w = pct(en.end_min) - l; if (w <= 0) return;
      var c = cat(en.category_id);
      segs += '<i class="seg" style="left:' + l.toFixed(2) + '%;width:' + w.toFixed(2) + '%;background:' + esc(c.color) +
        '" title="' + esc(c.name + ' ' + en.start + '–' + en.end) + '"></i>';
    });
    if (d.running && now != null) {
      var rl = pct(d.running.start_min), rw = pct(now) - rl;
      if (rw > 0) segs += '<i class="seg live" style="left:' + rl.toFixed(2) + '%;width:' + rw.toFixed(2) + '%;background:' + esc(cat(d.running.category_id).color) + '"></i>';
    }
    if (now != null && now < e) segs += '<i class="future" style="left:' + pct(now).toFixed(2) + '%"></i>';
    var step = len <= 600 ? 60 : 120, ticks = '';
    for (var t = Math.ceil(s / step) * step; t <= e; t += step) {
      var p = pct(t), cls = p < 3 ? ' first' : p > 97 ? ' last' : '';
      ticks += '<span class="tick' + cls + '" style="left:' + p.toFixed(2) + '%">' + pad(Math.floor(t / 60) % 24) + '</span>';
    }
    return '<div class="tl" role="img" aria-label="Timeline of the day">' + segs + '</div><div class="ticks" aria-hidden="true">' + ticks + '</div>' +
      '<div class="tl-note"><i></i>Hatched = not tracked</div>';
  }
  function renderToday() {
    var d = state.cache.day, el = $('#view-today'), u = state.me.user;
    var isToday = state.date === u.today;
    var h = '';
    h += '<div class="datebar"><button class="date-btn" data-act="prev" aria-label="Previous day">‹</button>' +
      '<div class="date-label">' + esc(dateLabel(state.date)) + '</div>' +
      '<button class="date-btn" data-act="next" aria-label="Next day"' + (isToday ? ' disabled' : '') + '>›</button></div>';
    h += todayReceipt(d);
    h += '<div class="card"><h3 class="card-title">Your day</h3>' + timelineHTML(d) + '</div>';
    if (d.limits && d.limits.length) {
      h += '<div class="card"><h3 class="card-title">Limits</h3>';
      d.limits.forEach(function (l) {
        var c = cat(l.category_id), over = l.used_min > l.limit_min;
        h += '<div class="limit-row"><div class="row-between"><span class="l">' + esc(c.emoji + ' ' + c.name) + '</span><span class="r' + (over ? ' over' : '') + '">' +
          dur(l.used_min) + ' / ' + durLimit(l.limit_min) + '</span></div><div class="bar"><i class="' + (over ? 'over' : '') +
          '" style="width:' + Math.min(100, l.used_min / l.limit_min * 100).toFixed(1) + '%"></i></div></div>';
      });
      h += '</div>';
    }
    h += '<h2 class="sec"><span>Entries</span><button class="btn small" data-act="add">+ Add entry</button></h2>';
    var runId = d.running ? d.running.entry_id : null, list = d.entries.filter(function (e) { return e.id !== runId && e.end_min != null; });
    if (d.running) list.push({ id: d.running.entry_id, category_id: d.running.category_id, start: d.running.start, end: 'now', start_min: d.running.start_min, end_min: null, note: null, _running: true });
    list.sort(function (a, b) { return a.start_min - b.start_min; });
    if (!list.length) h += '<div class="card empty">No entries for this day yet.</div>';
    else {
      h += '<div class="card entries">';
      list.forEach(function (en) {
        var c = cat(en.category_id);
        h += '<div class="entry"><span class="swatch" style="background:' + esc(c.color) + '"></span><div class="mid"><div class="name"><span>' + esc(c.emoji + ' ' + c.name) + '</span>' + (en._running ? '<span class="badge run">Running</span>' : '') + (c.is_waste ? '<span class="badge">Waste</span>' : '') + '</div>' +
          '<div class="note num">' + esc(en.start) + '\u2013' + esc(en.end) + (en.note ? ' \u00B7 ' + esc(en.note) : '') + '</div></div><div class="dur num"' + (en._running ? ' id="run-dur"' : '') + '>' + dur(en._running ? d.running.minutes : en.end_min - en.start_min) + '</div>' +
          '<button class="icon-btn" data-act="del-entry" data-id="' + en.id + '" aria-label="Delete entry ' + esc(c.name + ' ' + en.start) + '">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg></button></div>';
      });
      h += '</div>';
    }
    el.innerHTML = h;
  }

  /* add entry sheet */
  function openSheet(html) {
    var root = $('#sheet-root');
    root.innerHTML = '<div class="backdrop" data-act="close-sheet"></div><div class="sheet" role="dialog" aria-modal="true" aria-label="Add entry"><div class="grab"></div>' + html + '</div>';
    root.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(function () { root.classList.add('open'); });
    root._prevFocus = document.activeElement;
  }
  function closeSheet() {
    var root = $('#sheet-root');
    root.classList.remove('open'); root.setAttribute('aria-hidden', 'true');
    setTimeout(function () { if (!root.classList.contains('open')) root.innerHTML = ''; }, 260);
    if (root._prevFocus && root._prevFocus.focus) try { root._prevFocus.focus(); } catch (e) { /* ignore */ }
  }
  function openAddEntry() {
    var d = state.cache.day, now = nowMinOf(d);
    var end = now != null ? now : 12 * 60 + 30;
    end = Math.max(d.awake_start_min + 15, end);
    var start = Math.max(d.awake_start_min, end - 30);
    var opts = Object.keys(state.cats).map(function (k) { return state.cats[k]; }).filter(function (c) { return c.active; })
      .map(function (c) { return '<option value="' + c.id + '">' + esc(c.emoji + '  ' + c.name) + '</option>'; }).join('');
    openSheet('<h2>Add entry</h2><form id="entry-form" novalidate>' +
      '<label class="field"><span>Category</span><select name="cat" required>' + opts + '</select></label>' +
      '<div class="form-grid"><label class="field"><span>Start</span><input type="time" name="start" value="' + hhmm(start) + '" required></label>' +
      '<label class="field"><span>End</span><input type="time" name="end" value="' + hhmm(end) + '" required></label></div>' +
      '<label class="field"><span>Note (optional)</span><input type="text" name="note" maxlength="120" placeholder="Anything to remember"></label>' +
      '<p class="err" id="entry-err" hidden></p>' +
      '<div class="actions"><button type="button" class="btn ghost" data-act="close-sheet">Cancel</button><button type="submit" class="btn">Save</button></div></form>');
    setTimeout(function () { var s = $('#entry-form select'); if (s) s.focus(); }, 60);
  }
  function submitEntry(form) {
    var err = $('#entry-err'), btn = $('button[type=submit]', form);
    var f = form.elements, start = f.start.value, end = f.end.value;
    err.hidden = true;
    if (!start || !end) { err.textContent = 'Please set a start and end time.'; err.hidden = false; return; }
    if (end <= start) { err.textContent = 'End time must be after the start time.'; err.hidden = false; return; }
    btn.disabled = true;
    api('POST', '/api/entries', { category_id: +f.cat.value, date: state.date, start: start, end: end, note: f.note.value.trim() || null })
      .then(function () { haptic('success'); closeSheet(); toast('Entry added'); loadToday(); })
      .catch(function (e) { btn.disabled = false; haptic('error'); err.textContent = e.message || 'Could not save the entry.'; err.hidden = false; });
  }
  function deleteEntry(id) {
    confirmDlg('Delete this entry?').then(function (ok) {
      if (!ok) return;
      api('DELETE', '/api/entries/' + id).then(function () { haptic('success'); toast('Entry deleted'); loadToday(); })
        .catch(function (e) { toast(e.message || 'Could not delete.'); });
    });
  }

  /* ---------- Week ---------- */
  function loadWeek() {
    var tok = state.tokens.week = (state.tokens.week || 0) + 1;
    $('#view-week').innerHTML = skeleton('week');
    return api('GET', '/api/week').then(function (w) {
      if (tok !== state.tokens.week) return;
      state.cache.week = w; renderWeek();
    }).catch(function (e) {
      if (tok !== state.tokens.week) return;
      if (!handleFatal(e)) showError('week', e, loadWeek);
    });
  }
  function destroyChart(k) { if (charts[k]) { try { charts[k].destroy(); } catch (e) { /* ignore */ } charts[k] = null; } }
  function renderWeek() {
    var w = state.cache.week, el = $('#view-week'), u = state.me.user;
    destroyChart('week'); destroyChart('hours');
    var total = u.challenge_days, cd = u.challenge_day, byDate = {};
    w.days.forEach(function (d) { byDate[d.date] = d; });
    var dots = '', loggedN = 0;
    for (var k = 1; k <= total; k++) {
      var date = cd <= total ? addDays(u.today, k - cd) : addDays(w.end, k - total);
      var dd = byDate[date], on = !!(dd && dd.logged); if (on) loggedN++;
      dots += '<span class="dot' + (on ? ' on' : '') + (date === u.today ? ' today' : '') + '"></span>';
    }
    var daysWithData = w.days.filter(function (d) { return d.tracked_minutes > 0; }).length || 1;
    var perDay = w.waste_minutes / daysWithData;
    var peak = Math.max.apply(null, w.waste_by_hour), peakH = w.waste_by_hour.indexOf(peak);
    var h = '';
    h += '<div class="card challenge"><div><div class="t">' + (cd <= total ? 'Day ' + cd + ' of ' + total : 'Audit complete') + '</div>' +
      '<div class="muted small">' + loggedN + ' of ' + total + ' days logged</div></div><div class="dots" role="img" aria-label="' + loggedN + ' of ' + total + ' days logged">' + dots + '</div></div>';
    h += weekReceipt(w, perDay, daysWithData);
    h += '<div class="card"><h3 class="card-title">Each day</h3><div class="chart-box" id="box-week"><canvas id="ch-week" role="img" aria-label="Stacked bar chart of time per day by category"></canvas></div></div>';
    h += '<div class="card"><h3 class="card-title">When waste happens</h3><div class="chart-box short" id="box-hours"><canvas id="ch-hours" role="img" aria-label="Waste minutes by hour of day"></canvas></div>' +
      (peak > 0 ? '<div class="muted small" style="margin-top:8px">Busiest hour: ' + hhmm(peakH * 60) + '–' + hhmm(peakH * 60 + 60) + '</div>' : '') + '</div>';
    if (w.insight && w.insight.text) {
      var lines = String(w.insight.text).split('\n').map(function (l) { return l.replace(/^\s*[•\-\*]\s*/, '').trim(); }).filter(Boolean);
      h += '<div class="card insight"><h3 class="card-title">Weekly insight</h3><ul>' + lines.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join('') + '</ul></div>';
    }
    var tots = w.totals.slice().sort(function (a, b) { return b.minutes - a.minutes; }), max = tots.length ? tots[0].minutes : 1;
    h += '<div class="card"><h3 class="card-title">Where the time went</h3>';
    if (!tots.length) h += '<div class="muted">Nothing tracked yet.</div>';
    tots.forEach(function (t) {
      var c = cat(t.category_id);
      h += '<div class="cat" style="--c:' + esc(c.color) + '"><div class="row-between"><span class="l name"><span class="t">' + esc(c.emoji + ' ' + c.name) + '</span>' +
        (c.is_waste ? '<span class="badge">Waste</span>' : '') + '</span><span class="r num"><b style="color:var(--text)">' + dur(t.minutes) + '</b> · ' + dur(t.avg_per_day) + '/day</span></div>' +
        '<div class="bar"><i style="width:' + (t.minutes / max * 100).toFixed(1) + '%"></i></div></div>';
    });
    h += '</div>';
    el.innerHTML = h;
    if (state.tab === 'week') drawCharts(w);
  }
  function drawCharts(w) {
    var wb = $('#box-week'), hb = $('#box-hours');
    if (typeof window.Chart === 'undefined') {
      var msg = '<div class="chart-fallback">Charts couldn’t load. The numbers above and below are still accurate.</div>';
      if (wb) wb.outerHTML = msg; if (hb) hb.outerHTML = msg; return;
    }
    var Chart = window.Chart;
    var hint = css('--hint') || '#888', grid = css('--line') || 'rgba(0,0,0,.08)', card = css('--card') || '#fff', warm = css('--warm') || '#e07a2f';
    Chart.defaults.font.family = '-apple-system, "SF Pro Text", Inter, Roboto, sans-serif';
    Chart.defaults.font.size = 11;
    var yTick = function (v) { return v % 60 === 0 ? (v / 60) + 'h' : ''; };
    var tipBase = { backgroundColor: css('--text') || '#222', titleColor: css('--bg') || '#fff', bodyColor: css('--bg') || '#fff', footerColor: css('--bg') || '#fff', padding: 10, cornerRadius: 10, boxPadding: 4 };

    // stacked per-day chart: non-waste first (bottom), waste on top
    var cats = {}; w.days.forEach(function (d) { d.totals.forEach(function (t) { cats[t.category_id] = (cats[t.category_id] || 0) + t.minutes; }); });
    var ids = Object.keys(cats).map(Number).filter(function (id) { return cats[id] > 0; });
    ids.sort(function (a, b) { var ca = cat(a), cb = cat(b); return (ca.is_waste - cb.is_waste) || (cats[b] - cats[a]); });
    var datasets = ids.map(function (id) {
      var c = cat(id);
      return { label: c.emoji + ' ' + c.name, backgroundColor: c.color, borderColor: card, borderWidth: 1, borderSkipped: false, maxBarThickness: 30,
               data: w.days.map(function (d) { var t = d.totals.filter(function (x) { return x.category_id === id; })[0]; return t ? t.minutes : 0; }) };
    });
    charts.week = new Chart($('#ch-week'), {
      type: 'bar',
      data: { labels: w.days.map(function (d) { return d.label; }), datasets: datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, resizeDelay: 50,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, tipBase, { itemSort: function (a, b) { return b.datasetIndex - a.datasetIndex; }, callbacks: {
            label: function (c) { return c.parsed.y > 0 ? ' ' + c.dataset.label + ': ' + dur(c.parsed.y) : null; },
            footer: function (items) { var s = 0; items.forEach(function (i) { s += i.parsed.y; }); return 'Tracked: ' + dur(s); }
          } })
        },
        scales: {
          x: { stacked: true, grid: { display: false }, border: { display: false }, ticks: { color: hint } },
          y: { stacked: true, beginAtZero: true, border: { display: false }, grid: { color: grid }, ticks: { color: hint, stepSize: 120, callback: yTick } }
        }
      }
    });

    // waste by hour
    charts.hours = new Chart($('#ch-hours'), {
      type: 'bar',
      data: { labels: w.waste_by_hour.map(function (_, i) { return pad(i); }),
              datasets: [{ data: w.waste_by_hour, backgroundColor: warm, borderRadius: 3, borderSkipped: false, categoryPercentage: 0.9, barPercentage: 0.85 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, resizeDelay: 50,
        plugins: { legend: { display: false }, tooltip: Object.assign({}, tipBase, { displayColors: false, callbacks: {
          title: function (items) { var h = +items[0].label; return pad(h) + ':00–' + pad((h + 1) % 24) + ':00'; },
          label: function (c) { return dur(c.parsed.y) + ' of waste'; }
        } }) },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: hint, autoSkip: false, maxRotation: 0, callback: function (v, i) { return i % 3 === 0 ? pad(i) : ''; } } },
          y: { display: false, beginAtZero: true }
        }
      }
    });
  }

  function refreshCharts() {
    if (state.tab !== 'week') return;
    ['week', 'hours'].forEach(function (k) { var c = charts[k]; if (c) { try { c.resize(); c.update('none'); } catch (e) { /* ignore */ } } });
  }
  window.addEventListener('resize', function () { requestAnimationFrame(refreshCharts); });

  /* ---------- Goals ---------- */
  var LIMITS = [15, 30, 45, 60, 90, 120, 180];
  function loadGoals() {
    var tok = state.tokens.goals = (state.tokens.goals || 0) + 1;
    $('#view-goals').innerHTML = skeleton('goals');
    return api('GET', '/api/goals').then(function (g) {
      if (tok !== state.tokens.goals) return;
      state.cache.goals = g.goals; renderGoals();
    }).catch(function (e) {
      if (tok !== state.tokens.goals) return;
      if (!handleFatal(e)) showError('goals', e, loadGoals);
    });
  }
  function renderGoals() {
    var goals = state.cache.goals || [], el = $('#view-goals'), h = '';
    if (!goals.length) h += '<div class="card empty">No limits yet. Pick a category below that you would like to keep in check.</div>';
    goals.forEach(function (g) {
      var c = cat(g.category_id), used = g.today_used_min, lim = g.daily_limit_min, over = used > lim;
      h += '<div class="card goal"><div class="head"><b>' + esc(c.emoji + ' ' + c.name) + '</b>' +
        '<button class="icon-btn" data-act="del-goal" data-id="' + g.id + '" aria-label="Delete limit for ' + esc(c.name) + '">' +
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg></button></div>' +
        '<div class="row-between"><span class="l" style="font-weight:500">Today ' + dur(used) + ' / limit ' + durLimit(lim) + '</span>' +
        '<span class="r' + (over ? ' over' : '') + '">' + (over ? dur(used - lim) + ' over' : dur(lim - used) + ' left') + '</span></div>' +
        '<div class="bar"><i class="' + (over ? 'over' : '') + '" style="width:' + Math.min(100, used / lim * 100).toFixed(1) + '%"></i></div>' +
        '<div class="foot num">Week average ' + dur(g.week_avg_min) + '/day' + (g.baseline_avg_min != null ? ' · was ' + dur(g.baseline_avg_min) + '/day before' : '') + '</div></div>';
    });
    var wasteCats = Object.keys(state.cats).map(function (k) { return state.cats[k]; }).filter(function (c) { return c.is_waste && c.active; });
    h += '<h2 class="sec"><span>Add a limit</span></h2><form class="card" id="goal-form">' +
      '<label class="field"><span>Category</span><select name="cat">' + wasteCats.map(function (c) { return '<option value="' + c.id + '">' + esc(c.emoji + '  ' + c.name) + '</option>'; }).join('') + '</select></label>' +
      '<label class="field"><span>Daily limit</span><select name="limit">' + LIMITS.map(function (m) { return '<option value="' + m + '"' + (m === 60 ? ' selected' : '') + '>' + durLimit(m) + '</option>'; }).join('') + '</select></label>' +
      '<p class="muted small" style="margin:0 0 12px">A new limit replaces the current one for that category.</p>' +
      '<button class="btn block" type="submit"' + (wasteCats.length ? '' : ' disabled') + '>Set limit</button></form>';
    el.innerHTML = h;
  }

  /* ---------- tabs / events ---------- */
  function showTab(t, force) {
    state.tab = t;
    ['today', 'week', 'goals'].forEach(function (k) {
      var on = k === t;
      $('#tab-' + k).setAttribute('aria-selected', on ? 'true' : 'false');
      $('#view-' + k).hidden = !on;
    });
    if (t === 'week' && state.cache.week && force === false) renderWeek();
    if (force !== false) { if (t === 'today') loadToday(); else if (t === 'week') loadWeek(); else loadGoals(); }
    window.scrollTo(0, 0);
  }
  function go(delta) {
    var next = addDays(state.date, delta);
    if (next > state.me.user.today) return;
    state.date = next; haptic('select'); loadToday();
  }

  document.addEventListener('click', function (e) {
    var tab = e.target.closest('[data-tab]');
    if (tab) { if (tab.dataset.tab !== state.tab) haptic('select'); showTab(tab.dataset.tab); return; }
    var b = e.target.closest('[data-act]'); if (!b) return;
    var act = b.dataset.act;
    if (act === 'prev') go(-1);
    else if (act === 'next') go(1);
    else if (act === 'add') openAddEntry();
    else if (act === 'close-sheet') closeSheet();
    else if (act === 'del-entry') deleteEntry(+b.dataset.id);
    else if (act === 'del-goal') {
      confirmDlg('Delete this limit?').then(function (ok) {
        if (!ok) return;
        api('DELETE', '/api/goals/' + b.dataset.id).then(function () { toast('Limit deleted'); loadGoals(); }).catch(function (er) { toast(er.message || 'Could not delete.'); });
      });
    }
    else if (act === 'retry') { var v = b.closest('section'); if (v && v._retry) v._retry(); }
    else if (act === 'close') { try { tg.close(); } catch (er) { /* ignore */ } }
  });
  document.addEventListener('submit', function (e) {
    e.preventDefault();
    if (e.target.id === 'entry-form') submitEntry(e.target);
    else if (e.target.id === 'goal-form') {
      var f = e.target.elements, btn = $('button[type=submit]', e.target); btn.disabled = true;
      api('POST', '/api/goals', { category_id: +f.cat.value, daily_limit_min: +f.limit.value })
        .then(function () { haptic('success'); toast('Limit saved'); loadGoals(); })
        .catch(function (er) { btn.disabled = false; toast(er.message || 'Could not save.'); });
    }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && $('#sheet-root').classList.contains('open')) closeSheet(); });

  // live running timer
  setInterval(function () {
    var d = state.cache.day, el = document.getElementById('run-min');
    if (!d || !d.running || !el || state.tab !== 'today') return;
    var txt = dur(d.running.minutes + Math.floor((Date.now() - state.loadedAt) / 60000)), rd = document.getElementById('run-dur');
    el.textContent = txt; if (rd) rd.textContent = txt;
  }, 15000);

  /* ---------- boot ---------- */
  function boot() {
    try { if (tg) { tg.ready(); tg.expand(); } } catch (e) { /* not in Telegram */ }
    applyTheme();
    try { if (tg && tg.onEvent) tg.onEvent('themeChanged', function () { applyTheme(); if (state.tab === 'week' && state.cache.week) renderWeek(); }); } catch (e) { /* ignore */ }
    try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { if (state.tab === 'week' && state.cache.week) renderWeek(); }); } catch (e) { /* ignore */ }
    $('#view-today').innerHTML = skeleton('today');
    (MOCK ? loadScript('mock.js') : Promise.resolve()).then(function () { return api('GET', '/api/me'); }).then(function (me) {
      state.me = me; state.cats = {};
      me.categories.forEach(function (c) { state.cats[c.id] = c; });
      state.date = me.user.today;
      showTab('today');
    }).catch(function (e) {
      if (!handleFatal(e)) showError('today', e, boot);
    });
  }
  boot();
})();
