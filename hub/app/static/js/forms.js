/* Login, registration, preferences and group forms.
   Client-side checks are for UX only; the server re-validates everything against the OpenAPI contract. */
(function () {
  'use strict';
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
  var PHONE = /^(\+260|0)[79]\d{8}$/;

  function val(form, name) { var i = form.querySelector('[name="' + name + '"]'); return i ? i.value.trim() : ''; }

  function check(form, rules) {
    Hub.clearFieldErrors(form);
    var problems = [];
    Object.keys(rules).forEach(function (name) {
      var msg = rules[name](val(form, name));
      if (msg) {
        Hub.setFieldError(form, name, msg);
        var input = form.querySelector('[name="' + name + '"]');
        problems.push({ href: '#' + input.id, label: (form.querySelector('label[for="' + input.id + '"]') || {}).textContent || name, msg: msg });
      }
    });
    return problems;
  }

  function handle(formId, rules, submit) {
    var form = document.getElementById(formId);
    if (!form) return;
    var status = document.getElementById('status');
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var problems = check(form, rules);
      if (problems.length) {
        Hub.show(status, 'error', 'There ' + (problems.length === 1 ? 'is 1 problem' : 'are ' + problems.length + ' problems') + ' with the form', problems);
        form.querySelector('[aria-invalid="true"]').focus();
        return;
      }
      var btn = form.querySelector('button[type="submit"]');
      Hub.busy(btn, true);
      submit(form, status).then(function () { Hub.busy(btn, false); });
    });
  }

  var nextUrl = function (form) {
    var n = form.dataset.next || '/';
    return (n.charAt(0) === '/' && n.charAt(1) !== '/') ? n : '/';
  };

  document.addEventListener('DOMContentLoaded', function () {
    handle('login-form', {
      email: function (v) { return !v ? 'Enter your email address.' : (!EMAIL.test(v) ? 'Enter a valid email address.' : ''); },
      password: function (v) { return v ? '' : 'Enter your password.'; }
    }, function (form, status) {
      return Hub.api('POST', '/api/v1/auth/login', { email: val(form, 'email'), password: form.password.value }, { allow401: true })
        .then(function (r) {
          if (r.ok) location.href = nextUrl(form);
          else Hub.showProblem(status, r, form);
        });
    });

    handle('register-form', {
      full_name: function (v) { return v.length < 3 ? 'Full name must be at least 3 characters.' : ''; },
      email: function (v) { return !v ? 'Enter your email address.' : (!EMAIL.test(v) ? 'Enter a valid email address, for example name@mu.ac.zm.' : ''); },
      password: function (v) {
        if (v.length < 10) return 'Password must be at least 10 characters.';
        if (!/[A-Za-z]/.test(v) || !/\d/.test(v)) return 'Use at least one letter and one number.';
        return '';
      }
    }, function (form, status) {
      var role = form.querySelector('input[name="role"]:checked');
      return Hub.api('POST', '/api/v1/auth/register', {
        full_name: val(form, 'full_name'), email: val(form, 'email'), password: form.password.value,
        role: role ? role.value : 'student'
      }, { allow401: true }).then(function (r) {
        if (r.ok) location.href = r.data.role === 'organizer' ? '/organizer' : '/account#preferences';
        else Hub.showProblem(status, r, form);
      });
    });

    handle('prefs-form', {
      full_name: function (v) { return v.length < 3 ? 'Full name must be at least 3 characters.' : ''; },
      phone: function (v) {
        var opt = document.getElementById('whatsapp_opt_in');
        if (!v && opt && opt.checked) return 'Add your WhatsApp number to receive WhatsApp messages.';
        return v && !PHONE.test(v.replace(/\s/g, '')) ? 'Enter a Zambian number such as +260971234567 or 0971234567.' : '';
      }
    }, function (form, status) {
      var interests = Array.prototype.map.call(form.querySelectorAll('input[name="interests"]:checked'), function (c) { return c.value; });
      if (interests.length > 5) { Hub.show(status, 'error', 'Too many interests', 'Pick at most 5.'); return Promise.resolve(); }
      var phone = val(form, 'phone').replace(/\s/g, '');
      return Hub.api('PATCH', '/api/v1/me', {
        full_name: val(form, 'full_name'), interests: interests, phone: phone || null,
        whatsapp_opt_in: document.getElementById('whatsapp_opt_in').checked
      }).then(function (r) {
        if (r.ok) Hub.show(status, 'success', 'Preferences saved', 'Your recommendations will reflect these interests.');
        else Hub.showProblem(status, r, form);
      });
    });

    handle('group-form', {
      name: function (v) { return v.length < 3 ? 'Group name must be at least 3 characters.' : ''; },
      slug: function (v) { return /^[a-z0-9-]{2,60}$/.test(v) ? '' : 'Use 2-60 lowercase letters, numbers or dashes.'; },
      contact_email: function (v) { return v && !EMAIL.test(v) ? 'Enter a valid email address.' : ''; }
    }, function (form, status) {
      var body = { name: val(form, 'name'), slug: val(form, 'slug'), category: val(form, 'category'),
        description: val(form, 'description'), meeting_info: val(form, 'meeting_info') };
      if (val(form, 'contact_email')) body.contact_email = val(form, 'contact_email');
      return Hub.api('POST', '/api/v1/groups', body).then(function (r) {
        if (r.ok) { location.href = '/groups/' + r.data.slug; }
        else Hub.showProblem(status, r, form);
      });
    });

    var gname = document.getElementById('g-name'), gslug = document.getElementById('g-slug');
    if (gname && gslug) gname.addEventListener('input', function () {
      if (!gslug.dataset.touched) gslug.value = gname.value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60);
    });
    if (gslug) gslug.addEventListener('input', function () { gslug.dataset.touched = '1'; });
  });
})();
