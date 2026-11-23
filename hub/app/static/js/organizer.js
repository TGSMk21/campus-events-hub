/* Organizer dashboard: submit for approval, cancel, documents, attendee list. */
(function () {
  'use strict';
  var status;

  function loadDocs(bookingId) {
    var list = document.querySelector('[data-doc-list="' + bookingId + '"]');
    if (!list) return;
    Hub.api('GET', '/api/v1/bookings/' + bookingId + '/documents').then(function (r) {
      list.textContent = '';
      if (!r.ok) return list.appendChild(Hub.el('li', { text: 'Could not load documents.' }));
      if (!r.data.length) return list.appendChild(Hub.el('li', { class: 'muted', text: 'No documents yet.' }));
      r.data.forEach(function (d) {
        list.appendChild(Hub.el('li', {}, [Hub.el('a', { href: '/api/v1/documents/' + d.id, text: d.filename }),
          ' (' + Math.ceil(d.size_bytes / 1024) + ' KB, ' + d.uploaded_by_name + ')']));
      });
    });
  }
  window.HubDocs = { load: loadDocs };

  document.addEventListener('DOMContentLoaded', function () {
    status = document.getElementById('status');

    document.querySelectorAll('[data-docs-for]').forEach(function (det) {
      det.addEventListener('toggle', function () { if (det.open) loadDocs(det.dataset.docsFor); });
    });

    document.querySelectorAll('form[data-submit-event]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var att = Number(form.expected_attendance.value);
        if (!Number.isInteger(att) || att < 1 || att > 800) { Hub.show(status, 'error', 'Check the attendance', 'Expected attendance must be a whole number from 1 to 800.'); return; }
        var reqs = Array.prototype.map.call(form.querySelectorAll('input[name="requirements"]:checked'), function (c) { return c.value; });
        var btn = form.querySelector('button');
        Hub.busy(btn, true, 'Submitting…');
        Hub.api('POST', '/api/v1/events/' + form.dataset.submitEvent + '/submit', { expected_attendance: att, requirements: reqs }).then(function (r) {
          Hub.busy(btn, false);
          if (!r.ok) return Hub.showProblem(status, r);
          var lines = r.data.conflicts.map(function (c) { return 'Overlaps with ' + c.status + ' booking "' + c.event_title + '" (' + Hub.when(c.starts_at) + ')'; });
          Hub.show(status, lines.length ? 'info' : 'success', 'Venue request submitted',
            lines.length ? lines.concat(['An administrator will decide; you may want to pick another time.']) : 'An administrator will review it. You can attach an approval letter below.');
          setTimeout(function () { location.reload(); }, lines.length ? 4000 : 1500);
        });
      });
    });

    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-cancel-event]');
      if (!b) return;
      if (!confirm('Cancel "' + b.dataset.title + '"? All tickets will be cancelled and holders notified.')) return;
      Hub.busy(b, true);
      Hub.api('POST', '/api/v1/events/' + b.dataset.cancelEvent + '/cancel').then(function (r) {
        if (r.ok) { Hub.toast('Event cancelled'); setTimeout(function () { location.reload(); }, 600); }
        else { Hub.busy(b, false); Hub.showProblem(status, r); }
      });
    });

    document.querySelectorAll('form[data-upload]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        var file = form.file.files[0];
        if (!file) return Hub.show(status, 'error', 'Choose a file', 'Select a PDF or Word document to upload.');
        if (file.size > 5 * 1024 * 1024) return Hub.show(status, 'error', 'File too large', 'Files must be 5 MB or smaller.');
        var fd = new FormData();
        fd.append('file', file);
        var btn = form.querySelector('button');
        Hub.busy(btn, true, 'Uploading…');
        Hub.api('POST', '/api/v1/bookings/' + form.dataset.upload + '/documents', fd).then(function (r) {
          Hub.busy(btn, false);
          if (!r.ok) return Hub.showProblem(status, r);
          form.reset();
          Hub.toast('Uploaded ' + r.data.filename);
          loadDocs(form.dataset.upload);
        });
      });
    });

    document.addEventListener('click', function (e) {
      var b = e.target.closest('[data-attendees]');
      if (!b) return;
      Hub.api('GET', '/api/v1/events/' + b.dataset.attendees + '/attendees').then(function (r) {
        if (!r.ok) return Hub.showProblem(status, r);
        var body = document.getElementById('attendees-body'), panel = document.getElementById('attendees-panel');
        body.textContent = '';
        r.data.forEach(function (a) {
          body.appendChild(Hub.el('tr', {}, [Hub.el('td', { class: 'mono', text: a.ticket_code }), Hub.el('td', { text: a.full_name }),
            Hub.el('td', { text: a.email }), Hub.el('td', { text: a.paid ? 'Yes' : 'Free' })]));
        });
        panel.hidden = false;
        document.getElementById('attendees-title').focus();
      });
    });
  });
})();
