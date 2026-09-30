/* Read the collected Scholar total; the static site never scrapes Scholar. */
(function() {
  'use strict';

  var PROFILE_URL = 'https://scholar.google.com/citations?user=slhAlQ0AAAAJ&hl=en';
  var REQUEST_TIMEOUT = 8000;
  var SOURCES = [
    'assets/data/scholar.json',
    'https://raw.githubusercontent.com/yfyeung/yfyeung.github.io/main/assets/data/scholar.json'
  ];

  function parseTimestamp(value) {
    if (typeof value !== 'string')
      return null;
    var parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|\+00:00)$/.exec(value);
    if (!parts)
      return null;
    var timestamp = Date.parse(value);
    if (!Number.isFinite(timestamp) || timestamp > Date.now())
      return null;

    // Date.parse can normalize impossible dates such as February 30.
    var date = new Date(timestamp);
    if (date.getUTCFullYear() !== Number(parts[1])
        || date.getUTCMonth() + 1 !== Number(parts[2])
        || date.getUTCDate() !== Number(parts[3])
        || date.getUTCHours() !== Number(parts[4])
        || date.getUTCMinutes() !== Number(parts[5])
        || date.getUTCSeconds() !== Number(parts[6]))
      return null;
    return timestamp;
  }

  function validate(data) {
    if (!data || typeof data !== 'object' || Array.isArray(data)
        || data.profile_url !== PROFILE_URL
        || !Number.isSafeInteger(data.total_citations) || data.total_citations < 0)
      return null;
    var timestamp = parseTimestamp(data.updated_at);
    if (timestamp === null)
      return null;
    return { count: data.total_citations, timestamp: timestamp };
  }

  function fetchData(url) {
    var controller = typeof window.AbortController === 'function'
      ? new window.AbortController() : null;
    var timeoutId;
    var options = {
      headers: { Accept: 'application/json' },
      credentials: 'omit',
      cache: 'no-store'
    };
    if (controller)
      options.signal = controller.signal;

    var request = Promise.resolve().then(function() {
      return window.fetch(url, options);
    }).then(function(response) {
      if (!response || !response.ok)
        throw new Error('Scholar data request failed');
      return response.json();
    });

    var timeout = new Promise(function(resolve, reject) {
      timeoutId = window.setTimeout(function() {
        if (controller)
          controller.abort();
        reject(new Error('Scholar data request timed out'));
      }, REQUEST_TIMEOUT);
    });

    return Promise.race([request, timeout]).then(function(data) {
      window.clearTimeout(timeoutId);
      return data;
    }, function(error) {
      window.clearTimeout(timeoutId);
      throw error;
    });
  }

  function showTotal(targets, data) {
    var formatted = data.count.toLocaleString();
    var updated = new Date(data.timestamp).toISOString().replace('T', ' ').replace('Z', ' UTC');
    targets.forEach(function(target) {
      target.textContent = 'Google Scholar · ' + formatted + ' citations';
      target.setAttribute('aria-label', 'Google Scholar: ' + formatted + ' total citations across the profile');
      target.setAttribute('title', 'Total citations across this Google Scholar profile: '
        + formatted + '. Updated ' + updated + '.');
    });
  }

  function init() {
    var targets = document.querySelectorAll('a[data-scholar-citations]');
    if (!targets.length)
      return;
    targets.forEach(function(target) {
      target.setAttribute('href', PROFILE_URL);
    });
    if (typeof window.fetch !== 'function')
      return;

    var latest = null;
    SOURCES.forEach(function(url, priority) {
      fetchData(url).then(function(payload) {
        var data = validate(payload);
        if (!data || (latest && (data.timestamp < latest.timestamp
            || (data.timestamp === latest.timestamp && priority <= latest.priority))))
          return;
        // Prefer raw main for equal timestamps, regardless of response order.
        data.priority = priority;
        latest = data;
        showTotal(targets, data);
      }).catch(function() {
        // Keep a valid result from the other source, or the original Scholar link.
      });
    });
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', init, { once: true });
  else
    init();
})();
