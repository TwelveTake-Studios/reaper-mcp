# Contributing

Thanks for looking at this. Read the first section before you spend real effort, because
this repo is set up in a way that is not obvious and will otherwise waste your time.

## This repo is published from a private one

Development happens in a private working repo. This repo is published from it by a script
that copies an explicit allowlist of files: a file cannot appear here unless it has been named
as safe to publish, and a guard fails the sync if anything private is found in the tree.

That is deliberate. It exists so that notes, unreleased planning material and anything
personal cannot reach a public repo by accident, and it is a default-deny design on purpose:
nothing is published because someone judged it harmless, only because it was explicitly
listed.

**PRs are merged here.** Your commits land in this repo's history under your name, and the PR
reads as merged, because it was. The same change is then brought into the private repo so the
two agree. That second step is the maintainer's job and it has to happen before the next
publish, since the publish script treats the private copy as authoritative for file contents.

Two things follow from the setup that are worth knowing before you write a patch:

- **A PR that adds a new file needs that file added to the publish allowlist.** Mention it in
  the PR if your change adds one, so it doesn't end up sitting here ungoverned by the sync.
- **Only part of the test suite is public** (see the next section), so a change sometimes needs
  follow-up work to satisfy the private live suite. That is the maintainer's problem, not
  yours, and it is not a reason to hold back a patch.

Work that arrives some other way, an issue with a diagnosis precise enough to fix from, or a
fix already sitting in a fork, is credited in `CONTRIBUTORS.md` and as a co-author on the
commit that carries it. A clear diagnosis with a file and line number is worth as much here as
a patch, and costs you a lot less.

## What CI here does and does not cover

Public CI runs `ruff` and `pytest` across Linux, macOS and Windows on Python 3.10 to 3.13.
But only a subset of the test suite is public: the mocked marshalling tests, the headless
bridge tests that run real Lua under `lupa`, and the tool-surface checks. The live suite,
which drives a running REAPER, is private.

So a green check here does not guarantee the change passes everything. If a port needs
changes to satisfy the private suite, that is on the maintainer, not on you.

## Local setup

```bash
pip install -e ".[dev]"
python -m ruff check .
python -m pytest -q
```

`ruff` is usually not on PATH after that, hence `python -m ruff`.

To try a change against a real REAPER, deploy the bridge script and re-run it inside REAPER:

```bash
python reaper_mcp_server.py --install-bridge
```

REAPER runs the copy in its own Scripts folder, not the one in your checkout, so a bridge
change does nothing until you deploy it *and* re-run the script in REAPER
(Actions > Show action list > Load ReaScript).

## Things worth knowing before you change the bridge

- **Adding an entry to `DSL_FUNCTIONS` means bumping `MIN_BRIDGE_VERSION`.** The server checks
  the deployed bridge's version and refuses to run against one too old. Skip the bump and
  users with a stale script get a confusing per-tool error instead of "your bridge is out of
  date".
- **Array-valued fields must be wrapped in `as_array({})`** so an empty list serialises as
  `[]` and not `{}`. An entire release exists because that regressed once.
- **Errors use `{ok = false, error = "..."}`.** Match the shape of the handler next to yours.
- **A tool must not report success for work it did not do.** Several of the bugs fixed in
  1.6.1 were exactly this: an argument that never reached REAPER, with `ok: true` returned
  anyway.

## Tests

A test that passes both before and after your change is not a test. If you are fixing
something, break the fix on purpose and confirm the test goes red before you send it.

Response *shapes* cannot be pinned by the mocked suite, which only sees which function name
the server sent. If your change affects what the bridge returns, pin it in
`tests/test_bridge_encoder.py`, which runs the real Lua against a stub REAPER.
