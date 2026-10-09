/* Shared browser utilities. Feed strings are text; remote links must use HTTP(S). */
(function () {
  'use strict';
  function escapeText(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function httpURL(value) {
    try { var u = new URL(String(value)); return /^(https?:)$/.test(u.protocol) && !u.username && !u.password ? u.href : ''; }
    catch (_) { return ''; }
  }
  /* Defence in depth for trusted markup templates containing escaped feed text.
     Parse off-document and construct an allowlisted tree; never insert remote HTML. */
  function fragment(markup) {
    var parsed = new DOMParser().parseFromString(String(markup), 'text/html');
    var out = document.createDocumentFragment();
    var tags = ['DIV','SPAN','P','A','BUTTON','STRONG','B','EM','SMALL','H2','H3','UL','OL','LI','BR','OPTION'];
    function copy(node, parent) {
      if (node.nodeType === 3) { parent.appendChild(document.createTextNode(node.nodeValue)); return; }
      if (node.nodeType !== 1 || tags.indexOf(node.tagName) < 0) return;
      var el = document.createElement(node.tagName.toLowerCase());
      Array.from(node.attributes).forEach(function (attr) {
        var name = attr.name.toLowerCase(), value = attr.value;
        if (['class','id','title','value','type','role','hidden','disabled'].indexOf(name) >= 0 || /^(aria-|data-)/.test(name)) el.setAttribute(name, value);
        if (name === 'href') {
          var url = /^#[A-Za-z0-9_-]+$/.test(value) ? value : httpURL(value);
          if (url) el.setAttribute('href', url);
        }
        if (name === 'style' && !/[<>\\]|url\s*\(|expression|@import|javascript/i.test(value)) el.setAttribute('style', value);
        if (name === 'target' && value === '_blank') { el.target = '_blank'; el.rel = 'noopener noreferrer'; }
      });
      Array.from(node.childNodes).forEach(function (child) { copy(child, el); });
      parent.appendChild(el);
    }
    Array.from(parsed.body.childNodes).forEach(function (node) { copy(node, out); });
    return out;
  }
  function setHTML(el, markup) { el.replaceChildren(fragment(markup)); }
  function replaceHTML(el, markup) { el.replaceWith(fragment(markup)); }
  function text(tag, value, className) { var el = document.createElement(tag); el.textContent = String(value == null ? '' : value); if (className) el.className = className; return el; }
  function storageGet(key) { try { return localStorage.getItem(key); } catch (_) { return null; } }
  function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (_) {} }
  function fetchWithTimeout(input, init) {
    var timeoutMs = 12000, controller = typeof window.AbortController === 'function' ? new window.AbortController() : null;
    var options = init ? Object.assign({}, init) : {};
    if (controller && !options.signal) options.signal = controller.signal;
    var timer, rejectDeadline, settled = false;
    var deadline = new Promise(function (_, reject) { rejectDeadline = reject; });
    function stop() { if (settled) return; settled = true; clearTimeout(timer); }
    timer = setTimeout(function () {
      if (controller) { try { controller.abort(); } catch (_) {} }
      rejectDeadline(new Error('Request timed out after 12 seconds'));
    }, timeoutMs);
    var request;
    try { request = window.fetch(input, options); }
    catch (err) { stop(); return Promise.reject(err); }
    return Promise.race([request, deadline]).then(function (response) {
      if (response && response.ok === false) { stop(); return response; }
      ['json','text'].forEach(function (method) {
        if (typeof response[method] !== 'function') return;
        var original = response[method];
        response[method] = function () {
          var body;
          try { body = original.apply(response, arguments); }
          catch (err) { stop(); return Promise.reject(err); }
          return Promise.race([body, deadline]).then(function (value) { stop(); return value; }, function (err) { stop(); throw err; });
        };
      });
      return response;
    }, function (err) { stop(); throw err; });
  }
  var saved = storageGet('tools_compact');
  var requested = new URLSearchParams(location.search).get('compact');
  var declared = document.documentElement.getAttribute('data-compact');
  var compact = requested !== null ? requested === '1' : (declared !== null ? declared === '1' : (saved === null ? window.innerWidth <= 280 : saved === 'true'));
  document.documentElement.classList.toggle('compact', compact);
  window.ToolUI = {escape:escapeText, httpURL:httpURL, setHTML:setHTML, replaceHTML:replaceHTML, text:text, storageGet:storageGet, storageSet:storageSet, fetch:fetchWithTimeout};
  document.addEventListener('DOMContentLoaded', function () {
    var nav = document.createElement('nav'); nav.className = 'tool-nav'; nav.setAttribute('aria-label','Site');
    var prefix = document.body.classList.contains('game-page') ? '../' : '';
    var home = text('a','Home'); home.href = prefix + 'home.html';
    var services = text('a','Services'); services.href = prefix + 'home.html#services';
    var mode = text('button','Compact'); mode.type = 'button'; mode.setAttribute('aria-label','Toggle compact view'); mode.setAttribute('aria-pressed', String(compact));
    mode.addEventListener('click', function () {
      compact = !compact; document.documentElement.classList.toggle('compact',compact);
      mode.setAttribute('aria-pressed',String(compact)); storageSet('tools_compact',String(compact));
      var address = new URL(location.href); address.searchParams.set('compact',compact ? '1' : '0'); history.replaceState(null,'',address);
      document.dispatchEvent(new Event('tool-layout-change'));
    });
    nav.append(home,services,mode); document.body.insertBefore(nav,document.body.firstChild);
    document.querySelectorAll('.back-btn,.home-link').forEach(function (el) { el.hidden = true; });
    document.querySelectorAll('.last-update,#last-updated,.error,.config-error').forEach(function(el){el.setAttribute('role','status');});
  });
})();
