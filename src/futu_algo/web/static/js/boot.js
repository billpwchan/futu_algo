// Runs before first paint (classic script, no module) so an explicit theme choice does not flash.
(function () {
  try {
    var p = JSON.parse(window.localStorage.getItem('futu_algo.prefs') || '{}');
    var root = document.documentElement;
    var theme = p.theme || 'dark';
    if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme);
    root.setAttribute('data-updown', p.updown === 'red-up' ? 'red-up' : 'green-up');
  } catch (e) { document.documentElement.setAttribute('data-theme', 'dark'); }
})();
