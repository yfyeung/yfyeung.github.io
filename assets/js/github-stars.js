/* Public GitHub star counts, cached for six hours between page visits. */
(function() {
  'use strict';

  var CACHE_PREFIX = 'github-stars:v1:';
  var CACHE_TTL = 6 * 60 * 60 * 1000;
  var REQUEST_TIMEOUT = 8000;

  function validRepo(repo) {
    return typeof repo === 'string'
      && /^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?\/[a-z\d_.-]{1,100}$/i.test(repo)
      && !/^\.{1,2}$/.test(repo.split('/')[1]);
  }

  function validCount(count) {
    return typeof count === 'number' && Number.isSafeInteger(count) && count >= 0;
  }

  function readCache(repo) {
    try {
      var cached = JSON.parse(window.localStorage.getItem(CACHE_PREFIX + repo));
      if (cached && validCount(cached.count)
          && Number.isSafeInteger(cached.fetchedAt) && cached.fetchedAt > 0)
        return cached;
    }
    catch (error) {
      // Storage may be disabled, full, or contain an older/invalid value.
    }
    return null;
  }

  function writeCache(repo, count) {
    try {
      window.localStorage.setItem(CACHE_PREFIX + repo, JSON.stringify({
        count: count,
        fetchedAt: Date.now()
      }));
    }
    catch (error) {
      // A cache failure must not prevent displaying the fetched count.
    }
  }

  function showCount(targets, count) {
    var formatted = count.toLocaleString();
    targets.forEach(function(target) {
      target.count.textContent = formatted;
      target.badge.setAttribute('role', 'img');
      target.badge.setAttribute('aria-label', formatted + ' GitHub stars');
    });
  }

  function fetchCount(repo) {
    var controller = typeof window.AbortController === 'function'
      ? new window.AbortController() : null;
    var timeoutId;
    var options = {
      headers: { Accept: 'application/vnd.github+json' },
      credentials: 'omit'
    };
    if (controller)
      options.signal = controller.signal;

    var request = Promise.resolve().then(function() {
      return window.fetch('https://api.github.com/repos/' + repo, options);
    }).then(function(response) {
      if (!response || !response.ok)
        throw new Error('GitHub request failed');
      return response.json();
    }).then(function(data) {
      if (!data || !validCount(data.stargazers_count))
        throw new Error('Invalid GitHub star count');
      return data.stargazers_count;
    });

    var timeout = new Promise(function(resolve, reject) {
      timeoutId = window.setTimeout(function() {
        if (controller)
          controller.abort();
        reject(new Error('GitHub request timed out'));
      }, REQUEST_TIMEOUT);
    });

    return Promise.race([request, timeout]).then(function(count) {
      window.clearTimeout(timeoutId);
      return count;
    }, function(error) {
      window.clearTimeout(timeoutId);
      throw error;
    });
  }

  function init() {
    var repositories = new Map();
    document.querySelectorAll('[data-github-repo]').forEach(function(project) {
      var repo = project.getAttribute('data-github-repo');
      var badge = project.querySelector('.project-stars');
      var count = badge && badge.querySelector('[data-star-count]');
      if (!validRepo(repo) || !count)
        return;
      if (!repositories.has(repo))
        repositories.set(repo, []);
      repositories.get(repo).push({ badge: badge, count: count });
    });

    repositories.forEach(function(targets, repo) {
      var cached = readCache(repo);
      if (cached) {
        showCount(targets, cached.count);
        var age = Date.now() - cached.fetchedAt;
        if (age >= 0 && age < CACHE_TTL)
          return;
      }
      if (typeof window.fetch !== 'function')
        return;

      fetchCount(repo).then(function(count) {
        showCount(targets, count);
        writeCache(repo, count);
      }).catch(function() {
        // Keep the last known count, or the initial "Stars" label on first failure.
      });
    });
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', init, { once: true });
  else
    init();
})();
