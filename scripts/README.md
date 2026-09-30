# Website metrics

## GitHub stars

`assets/js/github-stars.js` refreshes the Icefall and Lhotse badges from the public
GitHub API on page visits, with a six-hour browser cache. Requests need no token.
The initial HTML includes the last verified counts from 2026-09-30: 1,511 for
`k2-fsa/icefall` and 1,154 for `lhotse-speech/lhotse`. These were retrieved from the
respective public `/repos/{owner}/{repo}` endpoints. The initial values keep the
badges useful when a first request is rate-limited; successful requests replace
them and populate the cache. A failed refresh keeps the last known count.

## Google Scholar citations

`update_scholar.py` reads the **All / Citations** value from Yifan Yang's public
[Google Scholar profile](https://scholar.google.com/citations?user=slhAlQ0AAAAJ&hl=en).
It uses the Python standard library and updates `assets/data/scholar.json`:

- `profile_url`: the public Google Scholar source.
- `total_citations`: a nonnegative integer, or `null` before the first successful fetch.
- `updated_at`: the successful fetch time in UTC, or `null` before the first successful fetch.

The initial snapshot deliberately has no citation count. The live profile could
not be reached from the development environment; a successful workflow run is
needed before a real count is displayed. Test fixture numbers are synthetic.

The **Update Google Scholar citations** workflow runs daily at 03:27 UTC, on
relevant changes pushed to `main`, and manually through GitHub Actions. It checks
the parser before fetching, limits the fetch to 90 seconds, and commits only the
snapshot to `main` using the repository's built-in `GITHUB_TOKEN`. No API key is
required. Actions must be enabled and repository rules must permit the workflow
to write to `main`.

Commits created using `GITHUB_TOKEN` do not trigger a GitHub Pages build. The page
therefore reads the current snapshot from
`https://raw.githubusercontent.com/yfyeung/yfyeung.github.io/main/assets/data/scholar.json`,
so metric updates do not need a Pages deployment. The deployed local JSON can be
used as a fallback; it reflects the last Pages build.

Google Scholar can time out or reject automated requests. A failed fetch,
CAPTCHA, changed table structure, or invalid count fails the workflow and keeps
the last successful snapshot intact. Check the Actions log and rerun manually
when the public profile is reachable. The updater does not bypass challenges.
After a successful run, `updated_at` records data freshness even if the count
has not changed.

Run the offline tests with:

```sh
python3 -B -m unittest discover -s tests -p 'test_update_scholar.py' -v
```

To fetch manually where Scholar is reachable:

```sh
timeout --signal=TERM --kill-after=5s 90s python3 -B scripts/update_scholar.py
```
