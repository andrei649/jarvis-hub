/* HF-1 — user access token.
 *
 * The server guards the assistant (/chat), personal memory, notes, code
 * execution and other user-facing routes with web._user_guard. On localhost
 * it is open by default; on a LAN / remote deployment the owner sets
 * JARVIS_USER_TOKEN and enters that same token here once. We store it in
 * localStorage ('hud.user_token') and attach it as X-User-Token to every
 * same-origin request by wrapping window.fetch — so the existing scattered
 * fetch() calls across the HUD need no changes. On a 401 we prompt once,
 * store the token, and retry the request transparently.
 *
 * Loaded before the app modules so the wrapper is in place before the first
 * request fires. Mirrors admin.js's 'hud.admin_token' pattern, one tier down.
 */
(function () {
  var KEY = 'hud.user_token';
  var nativeFetch = window.fetch.bind(window);

  function sameOrigin(url) {
    try {
      if (url.charAt(0) === '/') return true;          // relative → same origin
      return new URL(url, window.location.href).origin === window.location.origin;
    } catch (e) { return false; }
  }

  function withToken(init) {
    var tok = '';
    try { tok = localStorage.getItem(KEY) || ''; } catch (e) {}
    if (!tok) return init;
    init = init || {};
    var h = new Headers(init.headers || {});
    if (!h.has('X-User-Token')) h.set('X-User-Token', tok);
    init.headers = h;
    return init;
  }

  var prompting = false;
  function promptForToken() {
    if (prompting) return null;                         // never stack prompts
    prompting = true;
    var t = null;
    try {
      t = window.prompt('This Jarvis requires an access token.\nSet JARVIS_USER_TOKEN on the server, then enter it here:');
    } catch (e) {}
    prompting = false;
    if (t && t.trim()) {
      try { localStorage.setItem(KEY, t.trim()); } catch (e) {}
      return t.trim();
    }
    return null;
  }

  window.fetch = function (input, init) {
    // The HUD always calls fetch() with a string URL; for anything else
    // (e.g. a Request object) pass through untouched to avoid clobbering its
    // headers (init.headers would *replace*, not merge, a Request's headers).
    if (typeof input !== 'string' || !sameOrigin(input)) {
      return nativeFetch(input, init);
    }
    return nativeFetch(input, withToken(init)).then(function (resp) {
      if (resp.status === 401 && !(init && init.__authRetry)) {
        var t = promptForToken();
        if (t) {
          init = init || {};
          init.__authRetry = true;                      // one retry only
          return nativeFetch(input, withToken(init));
        }
      }
      return resp;
    });
  };

  // Small helper so a settings field can set/clear the token explicitly.
  window.JarvisAuth = {
    setToken: function (t) { try { localStorage.setItem(KEY, (t || '').trim()); } catch (e) {} },
    getToken: function () { try { return localStorage.getItem(KEY) || ''; } catch (e) { return ''; } },
    clear: function () { try { localStorage.removeItem(KEY); } catch (e) {} },
  };
})();
