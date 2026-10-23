(function () {
  'use strict';

  var form = document.getElementById('booking-form');
  var status = document.getElementById('status');
  var count = document.getElementById('description-count');
  var PHONE = /^(\+260|0)[79]\d{8}$/;
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  var now = new Date();
  var iso = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
  document.getElementById('event-date').min = iso;

  // Each rule returns an error message, or '' when the field is valid.
  var rules = {
    'full-name': function (v) {
      if (!v.trim()) return 'Enter your full name.';
      if (v.trim().length < 3) return 'Full name must be at least 3 characters.';
      return '';
    },
    'email': function (v) {
      if (!v.trim()) return 'Enter your email address.';
      if (!EMAIL.test(v.trim())) return 'Enter a valid email address, for example name@mu.ac.zm.';
      return '';
    },
    'phone': function (v) {
      if (!v.trim()) return 'Enter your WhatsApp phone number.';
      if (!PHONE.test(v.replace(/\s/g, ''))) return 'Enter a Zambian number such as +260971234567 or 0971234567.';
      return '';
    },
    'event-title': function (v) {
      if (!v.trim()) return 'Enter an event title.';
      if (v.trim().length < 5) return 'Event title must be at least 5 characters.';
      return '';
    },
    'category': function (v) { return v ? '' : 'Choose an event category.'; },
    'venue': function (v) { return v ? '' : 'Choose a venue.'; },
    'event-date': function (v) {
      if (!v) return 'Choose an event date.';
      if (v < iso) return 'Event date cannot be in the past.';
      return '';
    },
    'start-time': function (v) { return v ? '' : 'Choose a start time.'; },
    'end-time': function (v) {
      if (!v) return 'Choose an end time.';
      var s = document.getElementById('start-time').value;
      if (s && v <= s) return 'End time must be after the start time.';
      return '';
    },
    'attendance': function (v) {
      if (v === '') return 'Enter the expected attendance.';
      var n = Number(v);
      if (!Number.isInteger(n) || n < 1 || n > 800) return 'Attendance must be a whole number from 1 to 800.';
      return '';
    },
    'description': function (v) {
      var len = v.trim().length;
      if (!len) return 'Enter an event description.';
      if (len < 20) return 'Description must be at least 20 characters (currently ' + len + ').';
      if (len > 500) return 'Description must be 500 characters or fewer.';
      return '';
    },
    'terms': function (_v, el) { return el.checked ? '' : 'You must confirm the declaration to continue.'; }
  };

  function labelText(id) {
    var l = form.querySelector('label[for="' + id + '"]');
    return l.firstChild.textContent.trim();
  }

  function setState(el, id, message) {
    var err = document.getElementById(id + '-error');
    el.setAttribute('aria-invalid', message ? 'true' : 'false');
    err.textContent = message;
    err.hidden = !message;
  }

  function validateField(id) {
    var el = document.getElementById(id);
    var msg = rules[id](el.value, el);
    setState(el, id, msg);
    return msg;
  }

  function validateTicketType() {
    var chosen = form.querySelector('input[name="ticketType"]:checked');
    var err = document.getElementById('ticket-type-error');
    var msg = chosen ? '' : 'Choose whether the event is free or ticketed.';
    Array.prototype.forEach.call(form.querySelectorAll('input[name="ticketType"]'), function (r) {
      r.setAttribute('aria-invalid', msg ? 'true' : 'false');
    });
    err.textContent = msg;
    err.hidden = !msg;
    return msg;
  }

  // Real-time validation: validate on blur, then re-validate on every change once touched.
  Object.keys(rules).forEach(function (id) {
    var el = document.getElementById(id);
    var touched = false;
    el.addEventListener('blur', function () { touched = true; validateField(id); });
    var evt = (el.type === 'checkbox' || el.tagName === 'SELECT') ? 'change' : 'input';
    el.addEventListener(evt, function () {
      if (touched || el.getAttribute('aria-invalid') === 'true') validateField(id);
    });
  });
  document.getElementById('start-time').addEventListener('change', function () {
    if (document.getElementById('end-time').value) validateField('end-time');
  });
  Array.prototype.forEach.call(form.querySelectorAll('input[name="ticketType"]'), function (r) {
    r.addEventListener('change', validateTicketType);
  });

  var desc = document.getElementById('description');
  desc.addEventListener('input', function () {
    count.textContent = desc.value.length + ' of 500 characters used';
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var problems = [];
    Object.keys(rules).forEach(function (id) {
      var msg = validateField(id);
      if (msg) problems.push({ id: id, name: labelText(id), msg: msg });
    });
    var tmsg = validateTicketType();
    if (tmsg) problems.push({ id: 'ticket-free', name: 'Ticketing', msg: tmsg });

    if (problems.length) {
      status.className = 'summary is-error';
      var html = '<h2>There ' + (problems.length === 1 ? 'is 1 problem' : 'are ' + problems.length + ' problems') +
        ' with your request</h2><ul>';
      problems.forEach(function (p) {
        html += '<li><a href="#' + p.id + '">' + p.name + '</a>: ' + p.msg + '</li>';
      });
      status.innerHTML = html + '</ul>';
      document.getElementById(problems[0].id).focus();
    } else {
      status.className = 'summary is-success';
      status.innerHTML = '<h2>Request submitted</h2><p>Your venue booking request has been sent to the administrators for review.</p>';
      status.focus();
      form.reset();
    }
  });

  form.addEventListener('reset', function () {
    Array.prototype.forEach.call(form.querySelectorAll('[aria-invalid]'), function (el) { el.setAttribute('aria-invalid', 'false'); });
    Array.prototype.forEach.call(form.querySelectorAll('.error'), function (el) { el.hidden = true; el.textContent = ''; });
    count.textContent = '0 of 500 characters used';
  });
})();
