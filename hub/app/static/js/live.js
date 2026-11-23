/* Live updates over WebSocket (/ws/live): seat counts and venue availability.
   Reconnects with exponential backoff + jitter; answers server heartbeats. */
(function () {
  'use strict';
  var attempt = 0, ws = null, pill = null, staleVenue = false;

  function setState(state, text) {
    if (!pill) return;
    pill.dataset.state = state;
    var t = pill.querySelector('.live-text');
    if (t) t.textContent = text;
  }

  function updateSeats(msg) {
    Array.prototype.forEach.call(document.querySelectorAll('[data-seats-for="' + msg.event_id + '"]'), function (node) {
      var cap = Number(node.dataset.capacity);
      if (node.dataset.format === 'sold') { node.textContent = msg.tickets_sold + ' / ' + cap; return; }
      node.textContent = msg.seats_left === 0 ? 'Sold out' : msg.seats_left + ' of ' + cap + ' seats left';
      node.classList.toggle('out', msg.seats_left === 0);
      node.classList.toggle('low', msg.seats_left > 0 && msg.seats_left <= cap * 0.15);
    });
    var btn = document.getElementById('get-ticket');
    if (btn && btn.dataset.eventId === String(msg.event_id)) {
      if (msg.seats_left === 0) { btn.disabled = true; btn.textContent = 'Sold out'; }
    }
  }

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    setState('retry', attempt ? 'Reconnecting…' : 'Connecting…');
    ws = new WebSocket(proto + location.host + '/ws/live');
    ws.onopen = function () { attempt = 0; setState('open', 'Live'); };
    ws.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === 'ping') { ws.send(JSON.stringify({ type: 'pong' })); return; }
      if (msg.type === 'capacity') updateSeats(msg);
      if (msg.type === 'venue') {
        var cal = document.getElementById('venue-cal');
        if (cal && cal.dataset.venueId === String(msg.venue_id) && !staleVenue) {
          staleVenue = true;
          Hub.toast('This venue\'s calendar just changed. Reloading…');
          setTimeout(function () { location.reload(); }, 1500);
        }
      }
      if (msg.type === 'event_status' && document.body.dataset.page === 'events' && msg.status === 'published') {
        Hub.toast('A new event was just published. Refresh to see it.');
      }
    };
    ws.onclose = function () {
      var delay = Math.min(30000, 1000 * Math.pow(2, attempt)) + Math.floor(Math.random() * 400);
      attempt++;
      setState('retry', 'Offline, retrying in ' + Math.round(delay / 1000) + 's');
      setTimeout(connect, delay);
    };
  }

  document.addEventListener('DOMContentLoaded', function () {
    pill = document.getElementById('live-status');
    if ('WebSocket' in window) connect();
  });
})();
