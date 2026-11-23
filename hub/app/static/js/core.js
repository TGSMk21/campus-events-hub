/* Shared client helpers. Text from users or the server is only ever inserted with
   textContent / createElement, never innerHTML (context-aware output encoding, Lab 6). */
(function () {
  'use strict';

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k === 'class') node.className = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return node;
  }

  // fetch wrapper: JSON in, JSON or RFC 7807 problem out. Never throws on HTTP errors.
  function api(method, url, body, opts) {
    opts = opts || {};
    var init = { method: method, headers: { 'Accept': 'application/json' }, credentials: 'same-origin' };
    if (body instanceof FormData) init.body = body;
    else if (body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(url, init).then(function (res) {
      var ct = res.headers.get('content-type') || '';
      var parse = ct.indexOf('json') !== -1 ? res.json() : Promise.resolve(null);
      return parse.catch(function () { return null; }).then(function (data) {
        if (res.status === 401 && !opts.allow401) {
          location.href = '/login?next=' + encodeURIComponent(location.pathname);
        }
        return { ok: res.ok, status: res.status, data: data };
      });
    }, function () {
      return { ok: false, status: 0, data: { title: 'Network error', detail: 'Could not reach the server. Check your connection and try again.' } };
    });
  }

  function toast(message) {
    var region = document.getElementById('toasts');
    if (!region) return;
    var t = el('div', { class: 'toast', text: message });
    region.appendChild(t);
    setTimeout(function () { t.remove(); }, 5000);
  }

  // Render a status/summary box. kind: success | error | info | loading
  function show(statusEl, kind, title, lines) {
    if (!statusEl) return;
    statusEl.className = 'summary is-' + kind;
    statusEl.textContent = '';
    statusEl.appendChild(el('h2', { text: title }));
    if (Array.isArray(lines) && lines.length) {
      var ul = el('ul');
      lines.forEach(function (l) {
        if (l.href) ul.appendChild(el('li', {}, [el('a', { href: l.href, text: l.label }), ': ' + l.msg]));
        else ul.appendChild(el('li', { text: l }));
      });
      statusEl.appendChild(ul);
    } else if (lines) {
      statusEl.appendChild(el('p', { text: lines }));
    }
    if (kind !== 'loading') statusEl.focus();
  }

  function clear(statusEl) { if (statusEl) { statusEl.className = 'summary'; statusEl.textContent = ''; } }

  function setFieldError(form, name, message) {
    var input = form.querySelector('[name="' + name + '"]') || document.getElementById(name);
    if (!input) return false;
    var err = document.getElementById((input.id || name) + '-error');
    input.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (err) { err.textContent = message || ''; err.hidden = !message; }
    return true;
  }

  function clearFieldErrors(form) {
    Array.prototype.forEach.call(form.querySelectorAll('[aria-invalid="true"]'), function (i) { i.setAttribute('aria-invalid', 'false'); });
    Array.prototype.forEach.call(form.querySelectorAll('.error'), function (e) { e.hidden = true; e.textContent = ''; });
  }

  // Map an RFC 7807 problem (with errors[].field like "/email") onto the form, plus a summary.
  function showProblem(statusEl, res, form, fieldMap) {
    var p = res.data || {};
    var lines = [];
    (p.errors || []).forEach(function (e) {
      var name = e.field.replace(/^\/(query\/)?/, '').split('/')[0];
      name = (fieldMap && fieldMap[name]) || name;
      var placed = form && setFieldError(form, name, e.message);
      lines.push(placed ? { href: '#' + ((form.querySelector('[name="' + name + '"]') || {}).id || name), label: name.replace(/_/g, ' '), msg: e.message } : (name + ': ' + e.message));
    });
    var title = res.status === 0 ? p.title : (p.title || 'Error') + (res.status ? ' (HTTP ' + res.status + ')' : '');
    show(statusEl, 'error', title, lines.length ? lines : (p.detail || 'Please try again.'));
  }

  function busy(button, on, label) {
    if (!button) return;
    if (on) { button.dataset.label = button.textContent; button.disabled = true; button.textContent = label || 'Working…'; }
    else { button.disabled = false; if (button.dataset.label) button.textContent = button.dataset.label; }
  }

  function when(iso, opts) {
    return new Date(iso).toLocaleString('en-GB', Object.assign({ timeZone: 'Africa/Lusaka', weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }, opts || {}));
  }

  window.Hub = { el: el, api: api, toast: toast, show: show, clear: clear, showProblem: showProblem,
    setFieldError: setFieldError, clearFieldErrors: clearFieldErrors, busy: busy, when: when };

  document.addEventListener('DOMContentLoaded', function () {
    // Sign out: revoke the server session, then go home.
    document.addEventListener('click', function (e) {
      var t = e.target.closest('[data-action="logout"]');
      if (!t) return;
      api('POST', '/api/v1/auth/logout', undefined, { allow401: true }).then(function () { location.href = '/'; });
    });

    // Follow / unfollow a group.
    var follow = document.getElementById('follow-btn');
    if (follow) follow.addEventListener('click', function () {
      var on = follow.getAttribute('aria-pressed') === 'true';
      busy(follow, true);
      api(on ? 'DELETE' : 'POST', '/api/v1/groups/' + encodeURIComponent(follow.dataset.slug) + '/follow').then(function (r) {
        busy(follow, false);
        if (!r.ok) return toast((r.data && r.data.detail) || 'Something went wrong');
        follow.setAttribute('aria-pressed', on ? 'false' : 'true');
        follow.textContent = on ? 'Follow' : 'Following ✓';
        follow.className = 'btn ' + (on ? 'btn-primary' : 'btn-secondary');
        var c = document.getElementById('follower-count');
        if (c) c.textContent = String(Number(c.textContent) + (on ? -1 : 1));
        toast(on ? 'Unfollowed' : 'Following, so their events will appear in your recommendations');
      });
    });

    // Cancel a ticket (account page).
    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-cancel-ticket]');
      if (!b) return;
      if (!confirm('Cancel your ticket for "' + b.dataset.title + '"? Your seat will be released.')) return;
      busy(b, true);
      api('POST', '/api/v1/tickets/' + b.dataset.cancelTicket + '/cancel').then(function (r) {
        if (r.ok) { toast('Ticket cancelled'); setTimeout(function () { location.reload(); }, 600); }
        else { busy(b, false); toast((r.data && r.data.detail) || 'Could not cancel'); }
      });
    });
  });
})();
