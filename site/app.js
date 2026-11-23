/* Campus Event & Activities Hub: static concept demo.
   - "View as" switches between Student / Organizer / Admin (stands in for login + role-based access).
   - State lives in localStorage; BroadcastChannel syncs open tabs, so seat counts, approvals and chat
     update live across windows (stands in for the WebSocket channel of the full design).
   - Every value inserted into HTML goes through h() (HTML-escaping) to prevent XSS. */
(function () {
  'use strict';

  var KEY = 'ceh-demo-v1';
  var CATS = ['academic', 'club', 'sports', 'cultural', 'career'];
  var REQS = { projector: 'Projector and screen', sound: 'Sound system', seating: 'Extra seating' };
  var state, channel = 'BroadcastChannel' in window ? new BroadcastChannel('ceh-demo') : null;
  var main, filters = { q: '', category: '', available: false, free: false };

  // ------------------------------------------------------------ state --
  function load() {
    try { state = JSON.parse(localStorage.getItem(KEY)); } catch (e) { state = null; }
    if (!state || !state.events) { state = JSON.parse(JSON.stringify(window.SEED)); state.role = 'student'; save(true); }
  }
  function save(silent) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* private mode: keep in memory */ }
    if (channel && !silent) channel.postMessage('changed');
  }
  if (channel) channel.onmessage = function () { load(); render(true); };

  // ---------------------------------------------------------- helpers --
  function h(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(iso, opts) {
    return new Date(iso).toLocaleString('en-GB', opts || { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  }
  function time(iso) { return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }); }
  function money(k) { return k ? 'K' + Number(k).toFixed(2) : 'Free'; }
  function me() { return state.users[state.role]; }
  function venue(id) { return state.venues.find(function (v) { return v.id === Number(id); }); }
  function group(slug) { return state.groups.find(function (g) { return g.slug === slug; }); }
  function ev(id) { return state.events.find(function (e) { return e.id === Number(id); }); }
  function left(e) { return e.capacity - e.sold; }
  function myTicket(e) { return state.tickets.find(function (t) { return t.eventId === e.id && t.status === 'confirmed'; }); }
  function overlaps(a, b) { return new Date(a.startsAt) < new Date(b.endsAt) && new Date(b.startsAt) < new Date(a.endsAt); }
  function conflicts(b) {
    return state.bookings.filter(function (o) {
      return o.id !== b.id && o.venueId === b.venueId && (o.status === 'approved' || o.status === 'pending') && overlaps(o, b);
    });
  }
  function badge(cls, text) { return '<span class="badge ' + h(cls) + '">' + h(text) + '</span>'; }
  function cat(c) { return badge('cat-' + c, c.charAt(0).toUpperCase() + c.slice(1)); }
  function st(s) { return badge('st-' + s, s.charAt(0).toUpperCase() + s.slice(1)); }
  function code() { var a = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789', s = ''; for (var i = 0; i < 12; i++) s += a[Math.floor(Math.random() * a.length)]; return s; }

  function toast(msg) {
    var t = document.createElement('div');
    t.className = 'toast'; t.textContent = msg;
    document.getElementById('toasts').appendChild(t);
    setTimeout(function () { t.remove(); }, 4500);
  }
  function notify(template, text) {
    var u = me();
    state.notifications.unshift({ id: state.nextId++, to: u.email, channel: 'email', template: template, text: text, at: new Date().toISOString() });
    if (u.whatsapp && u.phone) state.notifications.unshift({ id: state.nextId++, to: u.phone, channel: 'whatsapp', template: template, text: text, at: new Date().toISOString() });
  }

  function seats(e) {
    var l = left(e), cls = l === 0 ? 'out' : (l <= e.capacity * 0.15 ? 'low' : '');
    return '<span class="seats ' + cls + '">' + (l === 0 ? 'Sold out' : l + ' of ' + e.capacity + ' seats left') + '</span>';
  }
  function card(e, reasons) {
    var d = new Date(e.startsAt), g = e.group && group(e.group);
    return '<article class="card' + (reasons ? ' rec' : '') + '">' +
      '<div class="card-top"><span class="date-block" aria-hidden="true"><small>' + h(d.toLocaleString('en-GB', { month: 'short' })) + '</small>' + h(d.getDate()) + '</span>' +
      '<div><h3><a href="#/event/' + e.id + '">' + h(e.title) + '</a></h3><div class="meta"><span>' + h(fmt(e.startsAt)) + ' – ' + h(time(e.endsAt)) + '</span>' +
      '<span>' + h(venue(e.venueId).name) + '</span>' + (g ? '<span>by ' + h(g.name) + '</span>' : '') + '</div></div></div>' +
      (reasons ? '<p class="reasons">' + h(reasons.join(' · ')) + '</p>' : '') +
      '<div class="foot">' + cat(e.category) + '<span class="price">' + h(money(e.price)) + '</span>' + seats(e) + '</div></article>';
  }
  function upcoming() {
    var now = Date.now();
    return state.events.filter(function (e) { return e.status === 'published' && new Date(e.startsAt) > now; })
      .sort(function (a, b) { return new Date(a.startsAt) - new Date(b.startsAt); });
  }

  // Rule-based recommendations: followed group +3, interest +2, past attendance +1, filling up +0.5.
  function recommendations() {
    var u = me(), past = state.tickets.map(function (t) { var e = ev(t.eventId); return e && e.category; });
    return upcoming().filter(function (e) { return !myTicket(e) && left(e) > 0; }).map(function (e) {
      var r = [], s = 0;
      if (e.group && state.follows.indexOf(e.group) !== -1) { s += 3; r.push('You follow ' + group(e.group).name); }
      if (u.interests.indexOf(e.category) !== -1) { s += 2; r.push('Matches your interest in ' + e.category); }
      if (past.indexOf(e.category) !== -1) { s += 1; r.push("You've attended " + e.category + ' events'); }
      if (e.sold / e.capacity >= 0.5) { s += 0.5; r.push('Filling up fast'); }
      return { e: e, s: s, r: r };
    }).filter(function (x) { return x.s >= 2; }).sort(function (a, b) { return b.s - a.s; }).slice(0, 3);
  }

  // ------------------------------------------------------------ pages --
  var pages = {};

  pages.home = function () {
    var q = filters.q.toLowerCase();
    var items = upcoming().filter(function (e) {
      return (!q || (e.title + ' ' + e.description).toLowerCase().indexOf(q) !== -1) &&
        (!filters.category || e.category === filters.category) && (!filters.available || left(e) > 0) && (!filters.free || !e.price);
    });
    var filtering = q || filters.category || filters.available || filters.free;
    var recs = !filtering && state.role === 'student' ? recommendations() : [];
    return '<section class="hero full-bleed" aria-labelledby="hero-title"><div class="inner">' +
      '<span class="live-pill" data-state="open"><span class="live-dot" aria-hidden="true"></span>Live: open this page in two tabs and book a ticket</span>' +
      '<h1 id="hero-title">What\'s on at Mulungushi</h1><p>Find talks, matches, club nights and career fairs, and see seats update live.</p>' +
      '<form class="filters" id="filter-form" role="search" aria-label="Filter events">' +
      '<div class="field grow m0"><label for="q">Search events</label><input type="search" id="q" value="' + h(filters.q) + '" placeholder="e.g. hackathon, football, careers"></div>' +
      '<div class="field m0"><label for="fcat">Category</label><select id="fcat"><option value="">All categories</option>' +
      CATS.map(function (c) { return '<option value="' + c + '"' + (filters.category === c ? ' selected' : '') + '>' + c.charAt(0).toUpperCase() + c.slice(1) + '</option>'; }).join('') + '</select></div>' +
      '<div class="checks"><div class="choice"><input type="checkbox" id="favail"' + (filters.available ? ' checked' : '') + '><label for="favail">Seats available</label></div>' +
      '<div class="choice"><input type="checkbox" id="ffree"' + (filters.free ? ' checked' : '') + '><label for="ffree">Free events only</label></div></div>' +
      '<div class="actions m0">' + (filtering ? '<button class="btn btn-secondary" type="button" data-action="clear-filters">Clear</button>' : '') + '</div>' +
      '</form></div></section><div class="page">' +
      (recs.length ? '<section aria-labelledby="recs-title"><h2 id="recs-title" class="mt0">Recommended for you</h2><p class="muted small">Based on groups you follow, your interests and past events. <a href="#/account">Change interests</a></p><div class="grid">' +
        recs.map(function (x) { return card(x.e, x.r); }).join('') + '</div></section>' : '') +
      '<section aria-labelledby="list-title"><h2 id="list-title"' + (recs.length ? '' : ' class="mt0"') + '>' + (filtering ? items.length + ' matching event' + (items.length === 1 ? '' : 's') : 'Upcoming events') + '</h2>' +
      (items.length ? '<div class="grid">' + items.map(function (e) { return card(e); }).join('') + '</div>' : '<div class="empty"><p><strong>No events found.</strong> Try removing a filter.</p></div>') +
      '</section></div>';
  };

  pages.event = function (id) {
    var e = ev(id);
    if (!e || (e.status !== 'published' && state.role === 'student')) return notFound();
    var g = e.group && group(e.group), t = myTicket(e), started = new Date(e.startsAt) < Date.now();
    var action = '';
    if (e.status !== 'published') action = '<p class="muted">This event is ' + h(e.status) + ' and not yet visible to students.</p>';
    else if (t) action = '<div class="summary is-success"><h2>You\'re going</h2><p>Ticket code <span class="mono ticket-code">' + h(t.code) + '</span></p></div>';
    else if (started) action = '<p class="muted">This event has started; tickets are closed.</p>';
    else if (state.role !== 'student') action = '<p class="muted small">Switch to the <strong>Student</strong> view to get a ticket.</p>';
    else action = '<button class="btn btn-primary" type="button" data-action="ticket" data-id="' + e.id + '"' + (left(e) === 0 ? ' disabled' : '') + '>' +
      (left(e) === 0 ? 'Sold out' : e.price ? 'Buy ticket · ' + h(money(e.price)) : 'Register (free)') + '</button>' +
      '<p class="hint">Your ticket is emailed to ' + h(me().email) + (me().whatsapp ? ' and sent on WhatsApp' : '') + '.</p>';
    var msgs = (state.chat[e.id] || []);
    return '<div class="page"><p class="small"><a href="#/">← All events</a></p><div class="two-col"><article>' +
      '<div class="actions mt0">' + cat(e.category) + (e.status !== 'published' ? st(e.status) : '') + '</div>' +
      '<h1>' + h(e.title) + '</h1><p class="muted">Organised by ' + h(state.users.organizer.name) + (g ? ' for <a href="#/group/' + h(g.slug) + '">' + h(g.name) + '</a>' : '') + '</p>' +
      '<p class="pre-line">' + h(e.description) + '</p>' +
      (e.status === 'published' ? '<section class="stack mt2" aria-labelledby="chat-title"><h2 id="chat-title">Live event room</h2>' +
        '<p class="muted small">Messages appear instantly in every open tab.</p>' +
        '<div class="chat-feed" role="log" aria-live="polite" aria-label="Chat messages">' +
        (msgs.length ? msgs.map(function (m) { return '<div class="chat-msg"><time>' + h(time(m.at)) + '</time><b>' + h(m.from) + '</b>' + h(m.text) + '</div>'; }).join('') : '<p class="muted small m0">No messages yet. Say hello!</p>') +
        '</div><form class="chat-form" id="chat-form" data-id="' + e.id + '"><label for="chat-input" class="visually-hidden">Message</label>' +
        '<input id="chat-input" type="text" maxlength="300" autocomplete="off" placeholder="Type a message…" required><button class="btn btn-primary" type="submit">Send</button></form></section>' : '') +
      '</article><aside class="panel stack" aria-label="Tickets and details"><dl class="facts">' +
      '<dt>When</dt><dd>' + h(fmt(e.startsAt, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })) + '<br>' + h(time(e.startsAt)) + ' – ' + h(time(e.endsAt)) + '</dd>' +
      '<dt>Where</dt><dd><a href="#/venues/' + e.venueId + '">' + h(venue(e.venueId).name) + '</a></dd>' +
      '<dt>Price</dt><dd class="price">' + h(money(e.price)) + '</dd><dt>Seats</dt><dd>' + seats(e) + '</dd></dl>' +
      '<div id="ticket-status" class="summary" role="status" aria-live="polite" tabindex="-1"></div>' + action + '</aside></div></div>';
  };

  pages.groups = function () {
    return '<div class="page"><div class="page-head"><div><h1>Clubs &amp; student groups</h1><p>Follow groups to see their events first in your recommendations.</p></div></div><div class="grid">' +
      state.groups.map(function (g) {
        var n = upcoming().filter(function (e) { return e.group === g.slug; }).length, f = state.follows.indexOf(g.slug) !== -1;
        return '<article class="card"><h3><a href="#/group/' + h(g.slug) + '">' + h(g.name) + '</a></h3><p class="muted small m0">' + h(g.description) + '</p>' +
          '<div class="foot">' + cat(g.category) + '<span class="small muted">' + (g.followers + (f ? 1 : 0)) + ' followers · ' + n + ' upcoming</span>' + (f ? badge('st-approved', 'Following') : '') + '</div></article>';
      }).join('') + '</div></div>';
  };

  pages.group = function (slug) {
    var g = group(slug);
    if (!g) return notFound();
    var f = state.follows.indexOf(slug) !== -1, items = upcoming().filter(function (e) { return e.group === slug; });
    return '<div class="page"><p class="small"><a href="#/groups">← All groups</a></p><div class="two-col"><div>' + cat(g.category) +
      '<h1 class="mt0">' + h(g.name) + '</h1><p>' + h(g.description) + '</p><h2>Upcoming events</h2>' +
      (items.length ? '<div class="grid">' + items.map(function (e) { return card(e); }).join('') + '</div>' : '<div class="empty"><p>No upcoming events yet.</p></div>') +
      '</div><aside class="panel stack"><dl class="facts"><dt>Followers</dt><dd>' + (g.followers + (f ? 1 : 0)) + '</dd><dt>Meets</dt><dd>' + h(g.meets) + '</dd></dl>' +
      '<button class="btn ' + (f ? 'btn-secondary' : 'btn-primary') + '" type="button" data-action="follow" data-slug="' + h(slug) + '" aria-pressed="' + f + '">' + (f ? 'Following ✓' : 'Follow') + '</button></aside></div></div>';
  };

  pages.venues = function (id) {
    var v = venue(id) || state.venues[0], start = new Date(); start.setHours(0, 0, 0, 0);
    var days = [];
    for (var i = 0; i < 14; i++) { var d = new Date(start); d.setDate(d.getDate() + i); days.push(d); }
    return '<div class="page"><div class="page-head"><div><h1>Venue availability</h1><p>Check for clashes before requesting a venue. Approved bookings are confirmed; pending ones await an admin.</p></div></div>' +
      '<div class="panel field-row align-end"><div class="field m0"><label for="venue-pick">Venue</label><select id="venue-pick">' +
      state.venues.map(function (x) { return '<option value="' + x.id + '"' + (x.id === v.id ? ' selected' : '') + '>' + h(x.name) + ' (capacity ' + x.capacity + ')</option>'; }).join('') +
      '</select></div><p class="m0 small muted">' + h(v.location) + ' · ' + h(v.facilities.join(', ')) + '</p></div>' +
      '<div class="cal mt1">' + days.map(function (d, i) {
        var end = new Date(d); end.setDate(end.getDate() + 1);
        var slots = state.bookings.filter(function (b) { return b.venueId === v.id && (b.status === 'approved' || b.status === 'pending') && new Date(b.startsAt) >= d && new Date(b.startsAt) < end; });
        return '<section class="day' + (i === 0 ? ' today' : '') + '" aria-label="' + h(d.toDateString()) + '"><h3>' + h(d.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' })) + '</h3>' +
          (slots.length ? slots.map(function (b) { return '<div class="slot ' + b.status + '">' + h(time(b.startsAt)) + '–' + h(time(b.endsAt)) + ' · ' + h(ev(b.eventId).title) + '<span class="visually-hidden"> (' + b.status + ')</span></div>'; }).join('') : '<p class="small muted m0">Free all day</p>') + '</section>';
      }).join('') + '</div><p class="small muted mt1"><span class="slot inline-block">Approved</span> <span class="slot pending inline-block">Pending review</span></p></div>';
  };

  pages.account = function () {
    var u = me(), mine = state.tickets.slice().reverse();
    return '<div class="page"><div class="page-head"><div><h1>My account</h1><p>' + h(u.name) + ' · ' + h(u.email) + ' · ' + h(u.role) + '</p></div></div><div class="two-col"><section class="stack">' +
      '<h2 class="mt0">My tickets</h2>' + (mine.length ? '<div class="table-wrap"><table><thead><tr><th scope="col">Event</th><th scope="col">When</th><th scope="col">Ticket</th><th scope="col"><span class="visually-hidden">Actions</span></th></tr></thead><tbody>' +
        mine.map(function (t) { var e = ev(t.eventId); return '<tr><td><a href="#/event/' + e.id + '">' + h(e.title) + '</a></td><td>' + h(fmt(e.startsAt)) + '</td><td><span class="mono">' + h(t.code) + '</span><br>' + st(t.status) + (t.paid ? ' ' + badge('', 'Paid') : '') + '</td><td>' +
          (t.status === 'confirmed' ? '<button class="btn btn-danger btn-sm" type="button" data-action="cancel-ticket" data-code="' + h(t.code) + '">Cancel</button>' : '') + '</td></tr>'; }).join('') +
        '</tbody></table></div>' : '<div class="empty"><p>No tickets yet. ' + (state.role === 'student' ? '<a href="#/">Find an event</a>.' : 'Switch to the Student view to book.') + '</p></div>') +
      '<h2>Notifications sent to me</h2><p class="small muted">Simulated email tickets and WhatsApp messages.</p>' + outbox(state.notifications.filter(function (n) { return n.to === u.email || n.to === u.phone; }).slice(0, 8)) +
      '</section><section class="panel"><h2 class="mt0">Preferences</h2><form id="prefs-form" novalidate><fieldset class="group"><legend>Interests</legend>' +
      CATS.map(function (c) { return '<div class="choice"><input type="checkbox" id="int-' + c + '" value="' + c + '"' + (u.interests.indexOf(c) !== -1 ? ' checked' : '') + '><label for="int-' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + '</label></div>'; }).join('') +
      '</fieldset><fieldset class="group"><legend>WhatsApp notifications</legend><div class="field"><label for="phone">WhatsApp number</label><input type="tel" id="phone" value="' + h(u.phone) + '" aria-describedby="phone-hint phone-error"><p id="phone-hint" class="hint">e.g. +260971234567 or 0971234567</p><p id="phone-error" class="error" hidden></p></div>' +
      '<div class="choice"><input type="checkbox" id="wa"' + (u.whatsapp ? ' checked' : '') + '><label for="wa">Send my tickets and updates on WhatsApp</label></div></fieldset>' +
      '<button class="btn btn-primary" type="submit">Save preferences</button></form></section></div></div>';
  };

  function outbox(list) {
    if (!list.length) return '<p class="muted small">Nothing yet.</p>';
    return '<div class="table-wrap"><table><thead><tr><th scope="col">Channel</th><th scope="col">To</th><th scope="col">Message</th><th scope="col">Status</th></tr></thead><tbody>' +
      list.map(function (n) { return '<tr><td>' + h(n.channel) + '</td><td class="small">' + h(n.to) + '</td><td class="small">' + h(n.text) + '</td><td>' + badge('st-simulated', 'Simulated') + '</td></tr>'; }).join('') + '</tbody></table></div>';
  }

  function bookingCard(b, admin) {
    var e = ev(b.eventId), c = conflicts(b);
    return '<article class="panel" aria-labelledby="b' + b.id + '"><div class="page-head m0"><div><h3 id="b' + b.id + '"><a href="#/event/' + e.id + '">' + h(e.title) + '</a></h3>' +
      '<p class="small">' + h(venue(b.venueId).name) + ' · ' + h(fmt(b.startsAt)) + '–' + h(time(b.endsAt)) + ' · ' + b.attendance + ' people' + (b.requirements.length ? ' · needs ' + h(b.requirements.join(', ')) : '') + '</p></div>' + st(b.status) + '</div>' +
      (b.note ? '<p class="small"><strong>Admin note:</strong> ' + h(b.note) + '</p>' : '') +
      (b.status === 'pending' ? (c.length ? c.map(function (o) { return '<p class="conflict' + (o.status === 'pending' ? ' soft' : '') + '">⚠ Overlaps with ' + o.status + ' booking “' + h(ev(o.eventId).title) + '” (' + h(fmt(o.startsAt)) + '–' + h(time(o.endsAt)) + ')' + (o.status === 'approved' && admin ? ': approving will be blocked.' : '') + '</p>'; }).join('') : '<p class="small muted">No clashes with other bookings.</p>') : '') +
      '<p class="small">Approval documents: ' + (b.documents.length ? b.documents.map(h).join(', ') : '<span class="muted">none</span>') + '</p>' +
      (!admin && b.status === 'pending' ? '<label class="small" for="doc-' + b.id + '">Attach approval letter (PDF/DOC, name only in this demo)</label><input type="file" id="doc-' + b.id + '" accept=".pdf,.doc,.docx" data-action="attach" data-id="' + b.id + '">' : '') +
      (admin && b.status === 'pending' ? '<form class="mt1" data-review="' + b.id + '" novalidate><div class="field"><label for="note-' + b.id + '">Note to organizer (required when rejecting)</label><input type="text" id="note-' + b.id + '" maxlength="300" aria-describedby="note-' + b.id + '-error"><p id="note-' + b.id + '-error" class="error" hidden></p></div>' +
        '<div class="actions m0"><button class="btn btn-ok btn-sm" type="submit" value="approve">Approve &amp; publish</button><button class="btn btn-danger btn-sm" type="submit" value="reject">Reject</button></div></form>' : '') + '</article>';
  }

  pages.organizer = function () {
    if (state.role === 'student') return forbidden('Organizers only', 'Switch “View as” to Organizer to manage events.');
    var mine = state.events.filter(function (e) { return e.organizerId === 2; }).sort(function (a, b) { return new Date(a.startsAt) - new Date(b.startsAt); });
    var bks = state.bookings.filter(function (b) { return ev(b.eventId).organizerId === 2; }).sort(function (a, b) { return b.id - a.id; });
    return '<div class="page"><div class="page-head"><div><h1>Organizer dashboard</h1><p>Create events, request venues and track ticket sales.</p></div><a class="btn btn-primary" href="#/new">+ New event</a></div>' +
      '<div id="status" class="summary" role="status" aria-live="polite" tabindex="-1"></div>' +
      '<div class="stat-row"><div class="stat"><b>' + mine.filter(function (e) { return e.status === 'published'; }).length + '</b>published events</div><div class="stat"><b>' +
      mine.reduce(function (s, e) { return s + e.sold; }, 0) + '</b>tickets issued</div><div class="stat"><b>' + bks.filter(function (b) { return b.status === 'pending'; }).length + '</b>requests pending</div></div>' +
      '<h2>My events</h2><div class="table-wrap"><table><thead><tr><th scope="col">Event</th><th scope="col">When &amp; where</th><th scope="col">Status</th><th scope="col">Tickets</th><th scope="col">Actions</th></tr></thead><tbody>' +
      mine.map(function (e) {
        return '<tr><td><a href="#/event/' + e.id + '">' + h(e.title) + '</a><br>' + cat(e.category) + ' <span class="small muted">' + h(money(e.price)) + '</span></td><td>' + h(fmt(e.startsAt)) + '<br><span class="small muted">' + h(venue(e.venueId).name) + '</span></td>' +
          '<td>' + st(e.status) + '</td><td>' + e.sold + ' / ' + e.capacity + '</td><td><div class="actions m0">' +
          (e.status === 'draft' || e.status === 'rejected' ? '<details class="inline"><summary>Request venue</summary><form data-submit-event="' + e.id + '" novalidate><div class="field"><label for="att-' + e.id + '">Expected attendance</label><input type="number" id="att-' + e.id + '" min="1" max="800" value="' + e.capacity + '" required></div>' +
            '<fieldset class="group"><legend>Venue requirements</legend>' + Object.keys(REQS).map(function (r) { return '<div class="choice"><input type="checkbox" id="r-' + e.id + '-' + r + '" value="' + r + '"><label for="r-' + e.id + '-' + r + '">' + REQS[r] + '</label></div>'; }).join('') + '</fieldset>' +
            '<button class="btn btn-primary btn-sm" type="submit">Submit for approval</button></form></details>' : '') +
          (e.status !== 'cancelled' ? '<button class="btn btn-danger btn-sm" type="button" data-action="cancel-event" data-id="' + e.id + '">Cancel</button>' : '') + '</div></td></tr>';
      }).join('') + '</tbody></table></div><h2>Venue requests</h2><div class="stack">' + bks.map(function (b) { return bookingCard(b, false); }).join('') + '</div></div>';
  };

  // The Lab 2 accessible venue booking form, evolved into "create event".
  pages['new'] = function () {
    if (state.role === 'student') return forbidden('Organizers only', 'Switch “View as” to Organizer to create events.');
    var today = new Date().toISOString().slice(0, 10);
    function field(id, label, input, hint) {
      return '<div class="field"><label for="' + id + '">' + label + '</label>' + input + (hint ? '<p id="' + id + '-hint" class="hint">' + hint + '</p>' : '') + '<p id="' + id + '-error" class="error" hidden></p></div>';
    }
    function desc(id, hint) { return ' aria-describedby="' + (hint ? id + '-hint ' : '') + id + '-error" aria-invalid="false"'; }
    return '<div class="page narrow"><p class="small"><a href="#/organizer">← Organizer dashboard</a></p><h1>Create an event</h1>' +
      '<p class="lead">Events start as drafts. Request the venue from your dashboard; an administrator reviews every request before the event is published.</p>' +
      '<div id="status" class="summary" role="status" aria-live="polite" tabindex="-1"></div><form id="event-form" novalidate><fieldset><legend>Event details</legend>' +
      field('title', 'Event title', '<input type="text" id="title" maxlength="80"' + desc('title', 1) + '>', 'Between 5 and 80 characters.') +
      '<div class="field-row">' + field('category', 'Category', '<select id="category"' + desc('category') + '><option value="">Choose a category</option>' + CATS.map(function (c) { return '<option value="' + c + '">' + c.charAt(0).toUpperCase() + c.slice(1) + '</option>'; }).join('') + '</select>') +
      field('group', 'Hosting group (optional)', '<select id="group"><option value="">No group</option>' + state.groups.map(function (g) { return '<option value="' + h(g.slug) + '">' + h(g.name) + '</option>'; }).join('') + '</select>') + '</div>' +
      field('description', 'Description', '<textarea id="description" rows="4" maxlength="500"' + desc('description', 1) + '></textarea>', 'Tell students what the event is about. Between 20 and 500 characters.') +
      '</fieldset><fieldset><legend>Venue and time</legend>' +
      field('venue', 'Venue', '<select id="venue"' + desc('venue', 1) + '><option value="">Choose a venue</option>' + state.venues.map(function (v) { return '<option value="' + v.id + '">' + h(v.name) + ' (capacity ' + v.capacity + ')</option>'; }).join('') + '</select>', 'Check the <a href="#/venues">venue calendar</a> for clashes first.') +
      '<div class="field-row">' + field('date', 'Date', '<input type="date" id="date" min="' + today + '"' + desc('date') + '>') + field('start', 'Start time', '<input type="time" id="start"' + desc('start') + '>') + field('end', 'End time', '<input type="time" id="end"' + desc('end') + '>') + '</div>' +
      '</fieldset><fieldset><legend>Tickets</legend><div class="field-row">' + field('capacity', 'Ticket capacity', '<input type="number" id="capacity" min="1" max="800"' + desc('capacity', 1) + '>', "Cannot exceed the venue's capacity.") +
      field('price', 'Price in Kwacha', '<input type="number" id="price" min="0" step="0.5" value="0"' + desc('price', 1) + '>', '0 for a free event. Paid tickets use a simulated checkout.') + '</div></fieldset>' +
      '<div class="actions"><button class="btn btn-primary" type="submit">Save draft</button><a class="btn btn-secondary" href="#/organizer">Cancel</a></div></form></div>';
  };

  pages.admin = function () {
    if (state.role !== 'admin') return forbidden('Administrators only', 'Switch “View as” to Admin to review venue requests.');
    var pending = state.bookings.filter(function (b) { return b.status === 'pending'; });
    var done = state.bookings.filter(function (b) { return b.status !== 'pending'; }).sort(function (a, b) { return b.id - a.id; }).slice(0, 8);
    return '<div class="page"><div class="page-head"><div><h1>Admin console</h1><p>Review venue requests and monitor notifications.</p></div></div>' +
      '<div id="status" class="summary" role="status" aria-live="polite" tabindex="-1"></div>' +
      '<h2>Pending venue requests (' + pending.length + ')</h2>' + (pending.length ? '<div class="stack">' + pending.map(function (b) { return bookingCard(b, true); }).join('') + '</div>' : '<div class="empty"><p>No requests waiting for review.</p></div>') +
      '<h2>Recently reviewed</h2><div class="table-wrap"><table><thead><tr><th scope="col">Event</th><th scope="col">Venue &amp; time</th><th scope="col">Status</th></tr></thead><tbody>' +
      done.map(function (b) { return '<tr><td>' + h(ev(b.eventId).title) + '</td><td>' + h(venue(b.venueId).name) + '<br><span class="small muted">' + h(fmt(b.startsAt)) + '</span></td><td>' + st(b.status) + '</td></tr>'; }).join('') +
      '</tbody></table></div><h2>Notification outbox</h2><p class="small muted">Email tickets and WhatsApp messages (simulated in this demo).</p>' + outbox(state.notifications.slice(0, 15)) + '</div>';
  };

  pages.help = function () {
    return '<div class="page narrow"><h1>About this demo</h1><p>The Campus Event &amp; Activities Hub helps students discover events and clubs, lets organizers request venues without clashes, and gives administrators one place to approve bookings.</p>' +
      '<h2>Try it</h2><ol><li><strong>Student:</strong> search events, follow a group, register for a free event or buy a ticket (simulated payment).</li>' +
      '<li><strong>Organizer:</strong> create an event (accessible form with real-time validation), then request a venue: overlapping bookings are flagged immediately.</li>' +
      '<li><strong>Admin:</strong> approve or reject requests. Approving a request that overlaps an approved booking is blocked.</li>' +
      '<li><strong>Live updates:</strong> open the site in two tabs. Tickets, approvals and chat messages appear in both instantly.</li></ol>' +
      '<h2>Scope covered</h2><ul><li>Roles: Student, Organizer, Admin (F-01)</li><li>Organizer dashboard and public event discovery with search/filters (F-02, F-03)</li><li>Clubs &amp; groups (F-04) and a rule-based recommendation feed (F-05)</li>' +
      '<li>Venue availability, booking requests and conflict detection (F-06), approval documents (F-07)</li><li>Free registration and simulated paid checkout with ticket codes (F-08)</li><li>Email/WhatsApp notifications, simulated (F-09)</li></ul>' +
      '<p class="muted small">ICT461 Advanced Web Technologies / ICT481 Software Project Management, Group 2, Mulungushi University.</p></div>';
  };

  function notFound() { return forbidden('Not found', "That page doesn't exist or isn't visible in this view."); }
  function forbidden(t, m) { return '<div class="page narrow"><h1>' + h(t) + '</h1><p>' + h(m) + '</p><p><a class="btn btn-primary" href="#/">Back to events</a></p></div>'; }

  // ------------------------------------------------------------ router --
  function route() {
    var parts = (location.hash.replace(/^#\/?/, '') || '').split('/');
    var name = parts[0] || 'home';
    if (name === 'venues' && parts[1]) return { name: 'venues', arg: parts[1] };
    return { name: pages[name] ? name : 'notfound', arg: parts[1] };
  }

  function nav() {
    var r = route().name, links = [['home', '#/', 'Events'], ['groups', '#/groups', 'Clubs & groups'], ['venues', '#/venues', 'Venues']];
    if (state.role !== 'student') links.push(['organizer', '#/organizer', 'Organizer']);
    if (state.role === 'admin') links.push(['admin', '#/admin', 'Admin']);
    links.push(['account', '#/account', 'My account'], ['help', '#/help', 'About']);
    document.getElementById('nav').innerHTML = links.map(function (l) {
      var cur = r === l[0] || (r === 'event' && l[0] === 'home') || (r === 'group' && l[0] === 'groups') || (r === 'new' && l[0] === 'organizer');
      return '<li><a href="' + l[1] + '"' + (cur ? ' aria-current="page"' : '') + '>' + h(l[2]) + '</a></li>';
    }).join('');
    document.getElementById('role').value = state.role;
  }

  function render(keepFocus) {
    var r = route(), active = document.activeElement, activeId = active && active.id, pos = active && active.selectionStart;
    nav();
    main.innerHTML = r.name === 'notfound' ? notFound() : pages[r.name](r.arg);
    main.classList.toggle('flush', r.name === 'home');
    if (keepFocus && activeId && document.getElementById(activeId)) {
      var el = document.getElementById(activeId);
      el.focus();
      if (pos != null && el.setSelectionRange) try { el.setSelectionRange(pos, pos); } catch (e) { /* not a text input */ }
    }
    var feed = main.querySelector('.chat-feed');
    if (feed) feed.scrollTop = feed.scrollHeight;
  }

  // ----------------------------------------------------------- actions --
  function modal(html) {
    var root = document.getElementById('modal-root');
    root.innerHTML = '<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' + html + '</div></div>';
    var first = root.querySelector('button');
    if (first) first.focus();
    return root;
  }
  function closeModal() { document.getElementById('modal-root').innerHTML = ''; }

  function issueTicket(e, paid) {
    // Mirrors the server transaction: re-check capacity and duplicates at the moment of issue.
    load();
    e = ev(e.id);
    if (left(e) <= 0) return { error: 'Sold out' };
    if (myTicket(e)) return { error: 'You already have a ticket for this event' };
    var t = { code: code(), eventId: e.id, status: 'confirmed', paid: paid, at: new Date().toISOString() };
    e.sold += 1;
    state.tickets.push(t);
    notify('ticket_confirmed', 'Your ticket for "' + e.title + '" on ' + fmt(e.startsAt) + ' is confirmed. Code: ' + t.code);
    save();
    return { ticket: t };
  }

  function showStatus(kind, title, msg) {
    var s = document.getElementById('status') || document.getElementById('ticket-status');
    if (!s) return toast(title + (msg ? ': ' + msg : ''));
    s.className = 'summary is-' + kind;
    s.innerHTML = '<h2>' + h(title) + '</h2>' + (Array.isArray(msg) ? '<ul>' + msg.map(function (m) { return '<li>' + (m.id ? '<a href="#' + h(m.id) + '" data-focus="' + h(m.id) + '">' + h(m.label) + '</a>: ' : '') + h(m.msg || m) + '</li>'; }).join('') + '</ul>' : '<p>' + h(msg || '') + '</p>');
    s.focus();
  }

  var actions = {
    ticket: function (btn) {
      var e = ev(btn.dataset.id);
      if (!e.price) {
        var r = issueTicket(e, false);
        render();
        if (r.error) showStatus('error', 'Could not register', r.error);
        else toast('Registered! Ticket ' + r.ticket.code + ' was emailed to you.');
        return;
      }
      modal('<h2 id="modal-title">Confirm payment</h2><div class="summary is-info"><h2>Sandbox</h2><p>This simulates a mobile-money prompt. No real money moves.</p></div>' +
        '<dl class="facts"><dt>Event</dt><dd>' + h(e.title) + '</dd><dt>Amount</dt><dd class="price">' + h(money(e.price)) + '</dd></dl>' +
        '<div class="actions"><button class="btn btn-ok" type="button" data-action="pay" data-id="' + e.id + '" data-outcome="success">Approve payment</button>' +
        '<button class="btn btn-danger" type="button" data-action="pay" data-id="' + e.id + '" data-outcome="decline">Decline</button></div>');
    },
    pay: function (btn) {
      var e = ev(btn.dataset.id);
      closeModal();
      if (btn.dataset.outcome === 'decline') {
        notify('payment_failed', 'Your payment for "' + e.title + '" was declined. No ticket was issued.');
        save(); render();
        return showStatus('error', 'Payment declined', 'No ticket was issued and you were not charged.');
      }
      var r = issueTicket(e, true);
      render();
      if (r.error) showStatus('error', 'Payment refunded', r.error + '. Your payment has been refunded.');
      else toast('Payment approved. Ticket ' + r.ticket.code + ' issued.');
    },
    follow: function (btn) {
      var i = state.follows.indexOf(btn.dataset.slug);
      if (i === -1) state.follows.push(btn.dataset.slug); else state.follows.splice(i, 1);
      save(); render();
      toast(i === -1 ? 'Following: their events will appear in your recommendations' : 'Unfollowed');
    },
    'cancel-ticket': function (btn) {
      var t = state.tickets.find(function (x) { return x.code === btn.dataset.code; });
      if (!t || !confirm('Cancel this ticket? Your seat will be released.')) return;
      t.status = 'cancelled'; ev(t.eventId).sold -= 1;
      save(); render(); toast('Ticket cancelled and seat released');
    },
    'cancel-event': function (btn) {
      var e = ev(btn.dataset.id);
      if (!confirm('Cancel "' + e.title + '"? All tickets will be cancelled and holders notified.')) return;
      e.status = 'cancelled'; e.sold = 0;
      state.bookings.forEach(function (b) { if (b.eventId === e.id && (b.status === 'pending' || b.status === 'approved')) b.status = 'cancelled'; });
      state.tickets.forEach(function (t) { if (t.eventId === e.id) t.status = 'cancelled'; });
      save(); render(); toast('Event cancelled');
    },
    'clear-filters': function () { filters = { q: '', category: '', available: false, free: false }; render(); }
  };

  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-action]');
    if (a && actions[a.dataset.action]) { e.preventDefault(); actions[a.dataset.action](a); }
    var f = e.target.closest('[data-focus]');
    if (f) { e.preventDefault(); var t = document.getElementById(f.dataset.focus); if (t) t.focus(); }
  });

  document.addEventListener('input', function (e) {
    if (e.target.id === 'q') { filters.q = e.target.value; render(true); }
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.id === 'role') { state.role = t.value; save(true); toast('Now viewing as ' + me().name + ' (' + t.value + ')'); render(); }
    if (t.id === 'fcat') { filters.category = t.value; render(true); }
    if (t.id === 'favail') { filters.available = t.checked; render(true); }
    if (t.id === 'ffree') { filters.free = t.checked; render(true); }
    if (t.id === 'venue-pick') location.hash = '#/venues/' + t.value;
    if (t.dataset.action === 'attach' && t.files[0]) {
      var b = state.bookings.find(function (x) { return x.id === Number(t.dataset.id); });
      var name = t.files[0].name;
      if (!/\.(pdf|docx?)$/i.test(name)) return showStatus('error', 'Unsupported file', 'Only PDF, DOC or DOCX files are accepted.');
      if (t.files[0].size > 5 * 1024 * 1024) return showStatus('error', 'File too large', 'Files must be 5 MB or smaller.');
      b.documents.push(name); save(); render(); toast('Attached ' + name);
    }
  });

  document.addEventListener('submit', function (e) {
    var f = e.target;
    e.preventDefault();
    if (f.id === 'event-form') return submitEvent(f);
    if (f.id === 'chat-form') {
      var input = f.querySelector('input'), text = input.value.trim();
      if (!text) return;
      (state.chat[f.dataset.id] = state.chat[f.dataset.id] || []).push({ from: me().name, text: text.slice(0, 300), at: new Date().toISOString() });
      input.value = '';
      save(); render(true);
      return;
    }
    if (f.id === 'prefs-form') {
      var u = me(), phone = document.getElementById('phone').value.replace(/\s/g, ''), wa = document.getElementById('wa').checked;
      var err = document.getElementById('phone-error'), inp = document.getElementById('phone');
      var msg = phone && !/^(\+260|0)[79]\d{8}$/.test(phone) ? 'Enter a Zambian number such as +260971234567.' : (wa && !phone ? 'Add a WhatsApp number to receive WhatsApp messages.' : '');
      inp.setAttribute('aria-invalid', msg ? 'true' : 'false'); err.textContent = msg; err.hidden = !msg;
      if (msg) return inp.focus();
      u.interests = CATS.filter(function (c) { return document.getElementById('int-' + c).checked; });
      u.phone = phone; u.whatsapp = wa;
      save(); render(); toast('Preferences saved');
      return;
    }
    if (f.dataset.submitEvent) {
      var ev1 = ev(f.dataset.submitEvent), att = Number(f.querySelector('input[type=number]').value), v = venue(ev1.venueId);
      if (!Number.isInteger(att) || att < 1) return showStatus('error', 'Check the attendance', 'Expected attendance must be a whole number of at least 1.');
      if (att > v.capacity) return showStatus('error', 'Too many people', v.name + ' holds at most ' + v.capacity + ' people.');
      var b = { id: state.nextId++, eventId: ev1.id, venueId: ev1.venueId, startsAt: ev1.startsAt, endsAt: ev1.endsAt, attendance: att,
        requirements: Array.prototype.map.call(f.querySelectorAll('input[type=checkbox]:checked'), function (c) { return c.value; }), status: 'pending', note: '', documents: [] };
      state.bookings.push(b); ev1.status = 'pending';
      notify('booking_submitted', 'Your request for ' + v.name + ' (' + ev1.title + ') is pending admin review.');
      save(); render();
      var c = conflicts(b);
      return c.length ? showStatus('info', 'Request submitted, but there is a clash', c.map(function (o) { return 'Overlaps with ' + o.status + ' booking "' + ev(o.eventId).title + '" (' + fmt(o.startsAt) + ')'; }))
        : showStatus('success', 'Venue request submitted', 'No clashes found. An administrator will review it.');
    }
    if (f.dataset.review) {
      var bk = state.bookings.find(function (x) { return x.id === Number(f.dataset.review); });
      var action = e.submitter ? e.submitter.value : 'approve', noteEl = f.querySelector('input'), note = noteEl.value.trim();
      var nErr = document.getElementById(noteEl.id + '-error');
      if (action === 'reject' && note.length < 5) {
        noteEl.setAttribute('aria-invalid', 'true'); nErr.textContent = 'Give the organizer a reason (at least 5 characters).'; nErr.hidden = false;
        return noteEl.focus();
      }
      var evt = ev(bk.eventId);
      if (action === 'approve') {
        // Same rule as the database EXCLUDE constraint: no two approved bookings may overlap in one venue.
        var clash = conflicts(bk).filter(function (o) { return o.status === 'approved'; })[0];
        if (clash) return showStatus('error', 'Cannot approve: venue already booked', '"' + ev(clash.eventId).title + '" is approved for an overlapping time. Reject this request or ask the organizer to change the time.');
        bk.status = 'approved'; evt.status = 'published';
      } else { bk.status = 'rejected'; evt.status = 'rejected'; }
      bk.note = note;
      state.notifications.unshift({ id: state.nextId++, to: state.users.organizer.email, channel: 'email', template: 'booking_' + bk.status,
        text: 'Your booking for "' + evt.title + '" was ' + bk.status + (note ? '. Note: ' + note : '.'), at: new Date().toISOString() });
      save(); render();
      showStatus('success', action === 'approve' ? 'Approved and published' : 'Request rejected', '"' + evt.title + '" ' + (action === 'approve' ? 'is now visible to students.' : 'was returned to the organizer.'));
    }
  });

  function submitEvent(f) {
    var g = function (id) { return document.getElementById(id); };
    var today = new Date().toISOString().slice(0, 10), v = venue(g('venue').value);
    var rules = {
      title: function (x) { x = x.trim(); return !x ? 'Enter an event title.' : x.length < 5 ? 'Event title must be at least 5 characters.' : ''; },
      category: function (x) { return x ? '' : 'Choose a category.'; },
      description: function (x) { var n = x.trim().length; return !n ? 'Enter a description.' : n < 20 ? 'Description must be at least 20 characters (currently ' + n + ').' : ''; },
      venue: function (x) { return x ? '' : 'Choose a venue.'; },
      date: function (x) { return !x ? 'Choose a date.' : x < today ? 'The date cannot be in the past.' : ''; },
      start: function (x) { return x ? '' : 'Choose a start time.'; },
      end: function (x) { return !x ? 'Choose an end time.' : g('start').value && x <= g('start').value ? 'End time must be after the start time.' : ''; },
      capacity: function (x) { var n = Number(x); return x === '' ? 'Enter the ticket capacity.' : !Number.isInteger(n) || n < 1 ? 'Capacity must be a whole number of at least 1.' : v && n > v.capacity ? 'Capacity cannot exceed the venue limit of ' + v.capacity + '.' : ''; },
      price: function (x) { return Number(x) < 0 ? 'Price must be 0 or more.' : ''; }
    };
    var problems = [];
    Object.keys(rules).forEach(function (id) {
      var msg = rules[id](g(id).value), err = g(id + '-error');
      g(id).setAttribute('aria-invalid', msg ? 'true' : 'false'); err.textContent = msg; err.hidden = !msg;
      if (msg) problems.push({ id: id, label: f.querySelector('label[for="' + id + '"]').textContent, msg: msg });
    });
    if (problems.length) {
      showStatus('error', 'There ' + (problems.length === 1 ? 'is 1 problem' : 'are ' + problems.length + ' problems') + ' with your event', problems);
      return g(problems[0].id).focus();
    }
    var d = g('date').value;
    state.events.push({ id: state.nextId++, group: g('group').value || null, title: g('title').value.trim(), category: g('category').value,
      venueId: v.id, startsAt: new Date(d + 'T' + g('start').value).toISOString(), endsAt: new Date(d + 'T' + g('end').value).toISOString(),
      capacity: Number(g('capacity').value), price: Number(g('price').value || 0), sold: 0, description: g('description').value.trim(), status: 'draft', organizerId: 2 });
    save();
    location.hash = '#/organizer';
    toast('Draft saved. Use “Request venue” to submit it for approval.');
  }

  // -------------------------------------------------------------- boot --
  document.addEventListener('DOMContentLoaded', function () {
    main = document.getElementById('main');
    load();
    window.addEventListener('hashchange', function () { closeModal(); render(); window.scrollTo(0, 0); main.focus(); });
    window.addEventListener('storage', function (e) { if (e.key === KEY) { load(); render(true); } });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeModal(); });
    document.getElementById('reset-demo').addEventListener('click', function () {
      if (!confirm('Reset all demo data to the starting state?')) return;
      localStorage.removeItem(KEY); load(); save(); render(); toast('Demo data reset');
    });
    render();
  });
})();
