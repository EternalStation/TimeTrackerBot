/* Mock API for ?mock=1. Same JSON shapes as SPEC section 13. Mutations live in memory only.
   Optional: &cd=4 simulates audit day 4 (no data before the challenge start, no previous week). */
(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var CD = Math.max(1, Math.min(14, parseInt(params.get('cd') || '7', 10) || 7));
  var TODAY = '2026-11-04';
  var T0 = Date.now();
  var NOW0 = 1300; // mock "now" = 21:40 on load, then it keeps ticking
  var WAKE = 480, SLEEP = 1380;

  var PAL_COOL = ['#4C7DF0', '#2BB3A3', '#7C5CDB', '#3A9BDC', '#5FA35A', '#8A94A6', '#C08B2C', '#2F6D8C', '#A3B86C'];
  var PAL_WARM = ['#F0564A', '#F28C38', '#E8487F', '#D9622B'];
  var DEFS = [
    ['Work', '💼', 0], ['Study', '📚', 0], ['Exercise', '🏃', 0],
    ['Chores & cooking', '🍳', 0], ['Eating', '🍽', 0], ['Commute', '🚌', 0],
    ['Friends & family', '👥', 0], ['Reading', '📖', 0], ['Rest', '😌', 0],
    ['Social media', '📱', 1], ['YouTube / TV', '📺', 1], ['Gaming', '🎮', 1]
  ];
  var cool = 0, warm = 0;
  var CATS = DEFS.map(function (d, i) {
    var color = d[2] ? PAL_WARM[warm++ % 4] : PAL_COOL[cool++ % 8]; // 9th cool category wraps around
    return { id: i + 1, name: d[0], emoji: d[1], is_waste: !!d[2], color: color, active: true };
  });
  var CAT = {}; CATS.forEach(function (c) { CAT[c.id] = c; });

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function hhmm(m) { return pad(Math.floor(m / 60)) + ':' + pad(m % 60); }
  function toMin(s) { var p = String(s).split(':'); return (+p[0]) * 60 + (+p[1]); }
  function addDays(s, n) {
    var p = s.split('-').map(Number);
    return new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)).toISOString().slice(0, 10);
  }
  function diffDays(a, b) { // b - a in days
    return Math.round((Date.parse(b + 'T00:00:00Z') - Date.parse(a + 'T00:00:00Z')) / 864e5);
  }
  function nowMin() { return Math.min(SLEEP - 1, NOW0 + Math.floor((Date.now() - T0) / 60000)); }
  function mulberry(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      var t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }
  function hash(s) { var h = 7; for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }

  var nextId = 100;
  var store = {};
  var running = { entry_id: 9001, category_id: 10, start_min: 1275 }; // 21:15 social media

  function genDay(date) {
    if (date > TODAY) return [];
    if (CD < 7 && date < addDays(TODAY, -(CD - 1))) return [];
    var rnd = mulberry(hash(date));
    var j = function (n) { return Math.round((rnd() - 0.5) * 2 * n / 5) * 5; };
    var dow = new Date(date + 'T00:00:00Z').getUTCDay();
    var weekend = dow === 0 || dow === 6;
    var older = diffDays(date, TODAY) >= 7;
    var gym = date === '2026-10-30' || date === '2026-11-02' || (older && (dow === 2 || dow === 4));
    var b = older ? 1.25 : 1; // slightly more waste in the previous week
    var c = WAKE, out = [];
    function add(cat, min, p) {
      if (p !== undefined && rnd() > p) return;
      min = Math.max(10, Math.round(min));
      var s = c, e = Math.min(SLEEP, c + min);
      if (e <= s) return;
      out.push({ id: nextId++, category_id: cat, start_min: s, end_min: e, source: 'checkin', note: null });
      c = e;
    }
    function gap(min, p) { if (p === undefined || rnd() <= p) c += min; }
    if (!weekend) {
      add(5, 25 + j(10)); add(6, 35); add(1, 185 + j(30)); add(5, 40 + j(10));
      add(10, 15 * b, 0.8); add(1, 230 + j(30)); gap(15, 0.5);
      if (gym) add(3, 70); else { add(6, 40); add(9, 20, 0.5); }
      add(4, 45); add(5, 30);
      add(10, 45 * b + j(10)); add(11, 50 * b + j(10)); gap(20);
      add(10, 35 * b); add(8, 25, 0.6);
    } else {
      add(4, 40); add(5, 30); add(9, 45); add(10, 20 * b); add(7, 140 + j(30)); add(5, 50);
      gap(20, 0.6); add(8, 50, 0.7);
      if (dow === 6) add(3, 60); else add(2, 60, 0.6);
      add(4, 40); add(5, 30); add(11, 70 * b + j(10)); add(10, 40 * b); gap(15); add(10, 30 * b); add(9, 30);
    }
    if (date === TODAY) {
      out = out.filter(function (x) { return x.start_min < running.start_min; });
      out.forEach(function (x) { if (x.end_min > running.start_min) x.end_min = running.start_min; });
      // two small gaps today
      out = out.filter(function (x) { return !(x.category_id === 9 && x.start_min > 1000); });
    }
    return out;
  }
  function entriesOf(date) { if (!store[date]) store[date] = genDay(date); return store[date]; }

  var goals = [
    { id: 3, category_id: 10, daily_limit_min: 60, baseline_avg_min: 130 },
    { id: 4, category_id: 11, daily_limit_min: 90, baseline_avg_min: 100 }
  ];
  var nextGoalId = 10;

  // All entries of a date incl. the running timer (for today), as plain intervals
  function intervals(date) {
    var list = entriesOf(date).map(function (x) { return { c: x.category_id, s: x.start_min, e: x.end_min }; });
    if (date === TODAY && running) list.push({ c: running.category_id, s: running.start_min, e: nowMin() });
    return list;
  }
  function statsFor(date) {
    var cap = date === TODAY ? Math.min(SLEEP, nowMin()) : SLEEP;
    var awake = Math.max(0, cap - WAKE);
    var tracked = 0, waste = 0, covered = 0, byCat = {};
    intervals(date).forEach(function (x) {
      var d = x.e - x.s; if (d <= 0) return;
      tracked += d; byCat[x.c] = (byCat[x.c] || 0) + d;
      if (CAT[x.c].is_waste) waste += d;
      covered += Math.max(0, Math.min(x.e, cap) - Math.max(x.s, WAKE));
    });
    var totals = Object.keys(byCat).map(function (k) { return { category_id: +k, minutes: byCat[k] }; })
      .sort(function (a, b) { return b.minutes - a.minutes; });
    return { awake: awake, tracked: tracked, waste: waste, untracked: Math.max(0, awake - covered), totals: totals, byCat: byCat, cap: cap };
  }

  function entryShape(x) {
    return { id: x.id, category_id: x.category_id, start: hhmm(x.start_min), end: hhmm(x.end_min),
             start_min: x.start_min, end_min: x.end_min, source: x.source, note: x.note };
  }
  function dayShape(date) {
    var st = statsFor(date);
    var isToday = date === TODAY;
    var lim = goals.map(function (g) {
      return { goal_id: g.id, category_id: g.category_id, limit_min: g.daily_limit_min, used_min: st.byCat[g.category_id] || 0 };
    });
    return {
      date: date, awake_start_min: WAKE, awake_end_min: SLEEP, awake_minutes: st.awake,
      tracked_minutes: st.tracked, untracked_minutes: st.untracked, waste_minutes: st.waste,
      waste_share: st.tracked ? Math.round(st.waste / st.tracked * 100) / 100 : 0,
      totals: st.totals,
      entries: entriesOf(date).slice().sort(function (a, b) { return a.start_min - b.start_min; }).map(entryShape),
      running: isToday && running ? {
        entry_id: running.entry_id, category_id: running.category_id, start: hhmm(running.start_min),
        start_min: running.start_min, minutes: Math.max(0, nowMin() - running.start_min)
      } : null,
      limits: lim
    };
  }
  function weekShape(end) {
    var days = [], byCat = {}, tracked = 0, untracked = 0, waste = 0, logged = 0, hours = [];
    for (var h = 0; h < 24; h++) hours.push(0);
    var withData = 0;
    for (var k = 6; k >= 0; k--) {
      var d = addDays(end, -k), st = statsFor(d);
      var isLogged = st.awake > 0 && st.tracked >= st.awake * 0.5;
      if (st.tracked > 0) withData++;
      if (isLogged) logged++;
      tracked += st.tracked; untracked += st.untracked; waste += st.waste;
      st.totals.forEach(function (t) { byCat[t.category_id] = (byCat[t.category_id] || 0) + t.minutes; });
      intervals(d).forEach(function (x) {
        if (!CAT[x.c].is_waste) return;
        for (var m = x.s; m < x.e; m++) hours[Math.min(23, Math.floor(m / 60))]++;
      });
      days.push({
        date: d, label: new Date(d + 'T00:00:00Z').toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }),
        tracked_minutes: st.tracked, untracked_minutes: st.untracked, waste_minutes: st.waste,
        logged: isLogged, totals: st.totals
      });
    }
    var n = Math.max(1, withData);
    var totals = Object.keys(byCat).map(function (k2) {
      return { category_id: +k2, minutes: byCat[k2], avg_per_day: Math.round(byCat[k2] / n) };
    }).sort(function (a, b) { return b.minutes - a.minutes; });
    var prev = null;
    if (CD >= 7) {
      prev = 0;
      for (var q = 7; q <= 13; q++) prev += statsFor(addDays(end, -q)).waste;
    }
    // insight text built from the mock numbers so it never contradicts the charts
    var topWaste = totals.filter(function (t) { return CAT[t.category_id].is_waste; })[0];
    var peak = hours.indexOf(Math.max.apply(null, hours));
    var fmt = function (m) { return m < 60 ? m + 'm' : Math.floor(m / 60) + 'h ' + pad(m % 60) + 'm'; };
    var text = [
      '• ' + CAT[topWaste.category_id].name + ' is your biggest waste category, about ' + fmt(topWaste.avg_per_day) + ' a day.',
      '• Waste peaks between ' + hhmm(peak * 60) + ' and ' + hhmm(peak * 60 + 60) + ', usually right after dinner.',
      '• A limit of 1h on social media is a realistic first step and still leaves room for an evening scroll.'
    ].join('\n');
    return {
      start: addDays(end, -6), end: end, days: days, totals: totals,
      tracked_minutes: tracked, untracked_minutes: untracked, waste_minutes: waste,
      waste_share: tracked ? Math.round(waste / tracked * 100) / 100 : 0,
      prev_waste_minutes: prev, days_logged: logged, waste_by_hour: hours,
      insight: { text: text, created_at: '2026-11-04T21:20:00Z' }
    };
  }
  function goalsShape() {
    var wk = weekShape(TODAY), st = statsFor(TODAY);
    return {
      goals: goals.map(function (g) {
        var t = wk.totals.filter(function (x) { return x.category_id === g.category_id; })[0];
        return { id: g.id, category_id: g.category_id, daily_limit_min: g.daily_limit_min,
                 today_used_min: st.byCat[g.category_id] || 0, week_avg_min: t ? t.avg_per_day : 0,
                 baseline_avg_min: g.baseline_avg_min };
      })
    };
  }
  function meShape() {
    return {
      user: { first_name: 'Alex', tz: '+01:00', wake_time: '08:00', sleep_time: '23:00', ping_interval_min: 60,
              paused: false, challenge_day: CD, challenge_days: 7, today: TODAY },
      categories: CATS
    };
  }

  function fail(status, code, message) { return { status: status, code: code, message: message }; }

  function postEntry(b) {
    var cat = CAT[b.category_id];
    if (!cat) throw fail(400, 'bad_category', 'Unknown category.');
    var date = b.date || TODAY;
    var s = toMin(b.start), e = toMin(b.end);
    if (!(e > s)) throw fail(400, 'bad_range', 'End must be after start.');
    if (date > TODAY) throw fail(400, 'future', 'That time is in the future.');
    if (date === TODAY && e > nowMin()) e = nowMin();
    if (e <= s) throw fail(400, 'future', 'That time is in the future.');
    var list = entriesOf(date), next = [];
    list.forEach(function (x) { // manual entries override what is underneath
      if (x.end_min <= s || x.start_min >= e) { next.push(x); return; }
      if (x.start_min < s) next.push({ id: x.id, category_id: x.category_id, start_min: x.start_min, end_min: s, source: x.source, note: x.note });
      if (x.end_min > e) next.push({ id: nextId++, category_id: x.category_id, start_min: e, end_min: x.end_min, source: x.source, note: x.note });
    });
    var entry = { id: nextId++, category_id: cat.id, start_min: s, end_min: e, source: 'manual', note: (b.note && String(b.note).trim()) || null };
    next.push(entry);
    store[date] = next;
    return { ok: true, entry: entryShape(entry) };
  }

  function route(method, url, body) {
    var u = new URL(url, location.origin), p = u.pathname, m;
    if (method === 'GET' && p === '/api/me') return meShape();
    if (method === 'GET' && p === '/api/day') return dayShape(u.searchParams.get('date') || TODAY);
    if (method === 'GET' && p === '/api/week') return weekShape(u.searchParams.get('end') || TODAY);
    if (method === 'GET' && p === '/api/goals') return goalsShape();
    if (method === 'POST' && p === '/api/entries') return postEntry(body || {});
    if (method === 'DELETE' && (m = p.match(/^\/api\/entries\/(\d+)$/))) {
      var id = +m[1], found = false;
      Object.keys(store).forEach(function (d) {
        var n = store[d].filter(function (x) { return x.id !== id; });
        if (n.length !== store[d].length) { found = true; store[d] = n; }
      });
      if (!found && running && running.entry_id === id) { running = null; found = true; }
      if (!found) throw fail(404, 'not_found', 'Entry not found.');
      return { ok: true };
    }
    if (method === 'POST' && p === '/api/goals') {
      var cid = +body.category_id, lim = +body.daily_limit_min;
      if (!CAT[cid] || !CAT[cid].is_waste) throw fail(400, 'bad_category', 'Pick a waste category.');
      var wk = weekShape(TODAY), t = wk.totals.filter(function (x) { return x.category_id === cid; })[0];
      goals = goals.filter(function (g) { return g.category_id !== cid; });
      var g = { id: nextGoalId++, category_id: cid, daily_limit_min: lim, baseline_avg_min: t ? t.avg_per_day : 0 };
      goals.push(g);
      return { ok: true, goal: g };
    }
    if (method === 'DELETE' && (m = p.match(/^\/api\/goals\/(\d+)$/))) {
      var before = goals.length;
      goals = goals.filter(function (g) { return g.id !== +m[1]; });
      if (goals.length === before) throw fail(404, 'not_found', 'Goal not found.');
      return { ok: true };
    }
    throw fail(404, 'not_found', 'Unknown mock route ' + method + ' ' + p);
  }

  window.MockAPI = {
    handle: function (method, url, body) {
      return new Promise(function (resolve, reject) {
        setTimeout(function () {
          try { resolve(JSON.parse(JSON.stringify(route(method, url, body)))); }
          catch (e) { reject(e); }
        }, 120);
      });
    }
  };
})();
