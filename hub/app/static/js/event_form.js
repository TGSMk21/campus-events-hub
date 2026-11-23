/* Create / edit event form. This is the Lab 2 accessible form with the Lab 3 dual-layer flow:
   real-time client checks for UX, then fetch() to the contract-validated API. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('event-form');
    if (!form) return;
    var status = document.getElementById('status');
    var eventId = form.dataset.eventId;
    var $ = function (id) { return document.getElementById(id); };
    var count = $('description-count');

    function pad(n) { return String(n).padStart(2, '0'); }
    function localParts(iso) {
      var d = new Date(iso);   // shown in the browser's timezone, which is CAT on campus
      return { date: d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()), time: pad(d.getHours()) + ':' + pad(d.getMinutes()) };
    }
    var today = localParts(new Date().toISOString()).date;
    $('date').min = today;
    if (form.dataset.starts) {
      var s = localParts(form.dataset.starts), e = localParts(form.dataset.ends);
      $('date').value = s.date; $('start_time').value = s.time; $('end_time').value = e.time;
    }

    function venueCap() { var o = $('venue_id').selectedOptions[0]; return o && o.dataset.capacity ? Number(o.dataset.capacity) : 800; }

    var rules = {
      title: function (v) { v = v.trim(); return !v ? 'Enter an event title.' : (v.length < 5 ? 'Event title must be at least 5 characters.' : ''); },
      category: function (v) { return v ? '' : 'Choose a category.'; },
      description: function (v) {
        var n = v.trim().length;
        if (!n) return 'Enter an event description.';
        if (n < 20) return 'Description must be at least 20 characters (currently ' + n + ').';
        return n > 500 ? 'Description must be 500 characters or fewer.' : '';
      },
      venue_id: function (v) { return v ? '' : 'Choose a venue.'; },
      date: function (v) { return !v ? 'Choose a date.' : (v < today ? 'The date cannot be in the past.' : ''); },
      start_time: function (v) { return v ? '' : 'Choose a start time.'; },
      end_time: function (v) {
        if (!v) return 'Choose an end time.';
        var s = $('start_time').value;
        return s && v <= s ? 'End time must be after the start time.' : '';
      },
      capacity: function (v) {
        if (v === '') return 'Enter the ticket capacity.';
        var n = Number(v), cap = venueCap();
        if (!Number.isInteger(n) || n < 1) return 'Capacity must be a whole number of at least 1.';
        return n > cap ? 'Capacity cannot exceed the venue limit of ' + cap + '.' : '';
      },
      price: function (v) {
        var n = Number(v || 0);
        return isNaN(n) || n < 0 ? 'Price must be 0 or more.' : (Math.round(n * 100) !== n * 100 ? 'Use at most two decimal places.' : '');
      }
    };

    function validate(id) {
      var input = $(id);
      var msg = rules[id](input.value);
      Hub.setFieldError(form, input.name, msg);
      return msg;
    }

    // Real-time validation: on blur, then on every change once a field has been touched (from Lab 2).
    Object.keys(rules).forEach(function (id) {
      var input = $(id), touched = false;
      input.addEventListener('blur', function () { touched = true; validate(id); });
      input.addEventListener(input.tagName === 'SELECT' ? 'change' : 'input', function () {
        if (touched || input.getAttribute('aria-invalid') === 'true') validate(id);
      });
    });
    $('start_time').addEventListener('change', function () { if ($('end_time').value) validate('end_time'); });
    $('venue_id').addEventListener('change', function () { if ($('capacity').value) validate('capacity'); });

    function updateCount() { count.textContent = $('description').value.length + ' of 500 characters used'; }
    $('description').addEventListener('input', updateCount);
    updateCount();

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var problems = [];
      Object.keys(rules).forEach(function (id) {
        var msg = validate(id);
        if (msg) problems.push({ href: '#' + id, label: document.querySelector('label[for="' + id + '"]').textContent, msg: msg });
      });
      if (problems.length) {
        Hub.show(status, 'error', 'There ' + (problems.length === 1 ? 'is 1 problem' : 'are ' + problems.length + ' problems') + ' with your event', problems);
        $(problems[0].href.slice(1)).focus();
        return;   // invalid forms never produce an HTTP request
      }
      var d = $('date').value;
      var body = {
        title: $('title').value.trim(),
        description: $('description').value.trim(),
        category: $('category').value,
        venue_id: Number($('venue_id').value),
        group_id: $('group_id').value ? Number($('group_id').value) : null,
        starts_at: new Date(d + 'T' + $('start_time').value).toISOString(),
        ends_at: new Date(d + 'T' + $('end_time').value).toISOString(),
        capacity: Number($('capacity').value),
        price_ngwee: Math.round(Number($('price').value || 0) * 100)
      };
      var btn = form.querySelector('button[type="submit"]');
      Hub.busy(btn, true, 'Saving…');
      Hub.show(status, 'loading', 'Saving your event…');
      Hub.api(eventId ? 'PATCH' : 'POST', '/api/v1/events' + (eventId ? '/' + eventId : ''), body).then(function (r) {
        Hub.busy(btn, false);
        if (r.ok) { location.href = '/organizer#event-' + r.data.id; return; }
        Hub.showProblem(status, r, form, { starts_at: 'start_time', ends_at: 'end_time', price_ngwee: 'price' });
      });
    });
  });
})();
