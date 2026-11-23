/* Sandbox payment page: approve or decline a pending simulated payment. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var box = document.getElementById('pay');
    var actions = document.getElementById('pay-actions');
    if (!box || !actions) return;
    var status = document.getElementById('status');
    actions.addEventListener('click', function (e) {
      var b = e.target.closest('[data-outcome]');
      if (!b) return;
      Array.prototype.forEach.call(actions.querySelectorAll('button'), function (x) { x.disabled = true; });
      Hub.show(status, 'loading', 'Processing payment…');
      Hub.api('POST', '/api/v1/payments/' + box.dataset.payment + '/simulate', { outcome: b.dataset.outcome }).then(function (r) {
        if (!r.ok) { Hub.showProblem(status, r); return; }
        actions.remove();
        document.getElementById('pay-status').textContent = r.data.status;
        if (r.data.status === 'succeeded') Hub.show(status, 'success', 'Payment approved', 'Your ticket code is ' + r.data.ticket_code + '. It has been emailed to you.');
        else Hub.show(status, 'error', 'Payment not completed', r.data.failure_reason || 'The payment was declined.');
      });
    });
  });
})();
