// Runs before first paint (classic script, no module) so an explicit theme choice does not flash.
(function () {
  try {
    var p = JSON.parse(window.localStorage.getItem('futu_algo.prefs') || '{}');
    var root = document.documentElement;
    if (p.theme === 'light' || p.theme === 'dark') root.setAttribute('data-theme', p.theme);
    root.setAttribute('data-updown', p.updown === 'red-up' ? 'red-up' : 'green-up');
  } catch (e) { /* storage blocked: follow the system theme */ }
})();
