/* Event page: free registration / simulated checkout, and the live chat room. */
(function () {
  'use strict';

  function initTicket() {
    var btn = document.getElementById('get-ticket');
    var status = document.getElementById('ticket-status');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var id = btn.dataset.eventId, mode = btn.dataset.mode;
      Hub.busy(btn, true, mode === 'checkout' ? 'Starting checkout…' : 'Registering…');
      Hub.show(status, 'loading', mode === 'checkout' ? 'Starting checkout…' : 'Reserving your seat…');
      Hub.api('POST', '/api/v1/events/' + id + '/' + mode).then(function (r) {
        if (r.ok && mode === 'checkout') { location.href = r.data.pay_url; return; }
        Hub.busy(btn, false);
        if (r.ok) {
          btn.remove();
          Hub.show(status, 'success', "You're going!", 'Ticket code ' + r.data.code + '. We have emailed it to you.');
        } else {
          Hub.showProblem(status, r);
        }
      });
    });
  }

  function initChat() {
    var box = document.getElementById('chat');
    if (!box) return;
    var feed = document.getElementById('chat-feed'), form = document.getElementById('chat-form');
    var input = document.getElementById('chat-input'), note = document.getElementById('chat-status');
    var attempt = 0, ws;

    function add(m) {
      var t = new Date(m.created_at).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Lusaka' });
      feed.appendChild(Hub.el('div', { class: 'chat-msg' }, [Hub.el('time', { text: t }), Hub.el('b', { text: m.sender }), m.body]));
      feed.scrollTop = feed.scrollHeight;
    }

    function connect() {
      var proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
      ws = new WebSocket(proto + location.host + '/ws/events/' + box.dataset.eventId + '/chat');
      ws.onopen = function () { attempt = 0; note.textContent = 'Connected.'; };
      ws.onmessage = function (ev) {
        var msg = JSON.parse(ev.data);
        if (msg.type === 'ping') return ws.send(JSON.stringify({ type: 'pong' }));
        if (msg.type === 'history') { feed.textContent = ''; msg.messages.forEach(add); if (!msg.messages.length) note.textContent = 'Connected. Be the first to say hello.'; }
        if (msg.type === 'chat') add(msg);
        if (msg.type === 'error') note.textContent = msg.detail;
      };
      ws.onclose = function (ev) {
        if (ev.code === 1008) { note.textContent = 'You need to be signed in to chat.'; return; }
        var delay = Math.min(30000, 1000 * Math.pow(2, attempt++)) + Math.floor(Math.random() * 400);
        note.textContent = 'Disconnected. Reconnecting in ' + Math.round(delay / 1000) + 's…';
        setTimeout(connect, delay);
      };
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ message: text }));
      input.value = '';
    });
    connect();
  }

  document.addEventListener('DOMContentLoaded', function () { initTicket(); initChat(); });
})();
