/* Admin console: review bookings, roles, venues, outbox. */
(function () {
  'use strict';

  function loadDocs(id) {
    var list = document.querySelector('[data-doc-list="' + id + '"]');
    Hub.api('GET', '/api/v1/bookings/' + id + '/documents').then(function (r) {
      list.textContent = '';
      if (!r.ok || !r.data.length) return list.appendChild(Hub.el('li', { class: 'muted', text: r.ok ? 'No documents attached.' : 'Could not load.' }));
      r.data.forEach(function (d) { list.appendChild(Hub.el('li', {}, [Hub.el('a', { href: '/api/v1/documents/' + d.id, text: d.filename }), ' · ' + d.uploaded_by_name])); });
    });
  }

  function loadUsers(q) {
    var body = document.getElementById('users-body');
    Hub.api('GET', '/api/v1/admin/users' + (q ? '?q=' + encodeURIComponent(q) : '')).then(function (r) {
      body.textContent = '';
      if (!r.ok) return;
      r.data.forEach(function (u) {
        var sel = Hub.el('select', { 'aria-label': 'Role for ' + u.full_name, 'data-user': u.id });
        ['student', 'organizer', 'admin'].forEach(function (role) {
          var o = Hub.el('option', { value: role, text: role });
          if (role === u.role) o.selected = true;
          sel.appendChild(o);
        });
        body.appendChild(Hub.el('tr', {}, [Hub.el('td', { text: u.full_name }), Hub.el('td', { text: u.email }), Hub.el('td', {}, [sel])]));
      });
    });
  }

  function loadOutbox() {
    var body = document.getElementById('outbox-body');
    Hub.api('GET', '/api/v1/admin/notifications').then(function (r) {
      body.textContent = '';
      if (!r.ok || !r.data.length) return body.appendChild(Hub.el('tr', {}, [Hub.el('td', { colspan: '6', class: 'muted', text: 'No notifications yet.' })]));
      r.data.forEach(function (n) {
        body.appendChild(Hub.el('tr', {}, [Hub.el('td', { text: String(n.id) }), Hub.el('td', { text: n.user_email }), Hub.el('td', { text: n.channel }),
          Hub.el('td', { text: n.template.replace(/_/g, ' ') }), Hub.el('td', {}, [Hub.el('span', { class: 'badge st-' + n.status, text: n.status })]),
          Hub.el('td', { class: 'small', text: Hub.when(n.created_at) })]));
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var status = document.getElementById('status');

    document.querySelectorAll('[data-docs-for]').forEach(function (det) {
      det.addEventListener('toggle', function () { if (det.open) loadDocs(det.dataset.docsFor); });
    });

    document.querySelectorAll('form[data-review]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var action = e.submitter ? e.submitter.value : 'approve';
        var note = form.note.value.trim();
        if (action === 'reject' && note.length < 5) {
          Hub.setFieldError(form, 'note', 'Give the organizer a reason (at least 5 characters).');
          form.note.focus();
          return;
        }
        Hub.busy(e.submitter, true);
        Hub.api('POST', '/api/v1/bookings/' + form.dataset.review + '/' + action, note ? { note: note } : {}).then(function (r) {
          Hub.busy(e.submitter, false);
          if (!r.ok) return Hub.showProblem(status, r);
          Hub.toast(action === 'approve' ? 'Approved, and the event is now published' : 'Request rejected');
          document.getElementById('booking-' + form.dataset.review).remove();
          loadOutbox();
        });
      });
    });

    document.getElementById('user-search').addEventListener('submit', function (e) { e.preventDefault(); loadUsers(this.q.value.trim()); });
    document.getElementById('users-body').addEventListener('change', function (e) {
      var sel = e.target.closest('select[data-user]');
      if (!sel) return;
      Hub.api('PATCH', '/api/v1/admin/users/' + sel.dataset.user, { role: sel.value }).then(function (r) {
        if (r.ok) Hub.toast('Role updated to ' + r.data.role + '. Their sessions were signed out.');
        else { Hub.showProblem(status, r); loadUsers(document.getElementById('uq').value.trim()); }
      });
    });

    document.getElementById('venue-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = this;
      Hub.api('POST', '/api/v1/venues', { name: f.name.value.trim(), slug: f.slug.value.trim(), capacity: Number(f.capacity.value), location: f.location.value.trim() })
        .then(function (r) {
          if (r.ok) { Hub.toast('Venue added'); setTimeout(function () { location.reload(); }, 600); }
          else Hub.showProblem(status, r, f);
        });
    });

    loadUsers('');
    loadOutbox();
  });
})();
