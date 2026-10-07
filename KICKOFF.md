# Kickoff prompt

Paste everything below the line into Claude Code, started inside this folder.

---

Read `CLAUDE.md`, then `SPEC.md` in full, then `design/README.md` and the three mockup files in `design/`.

Before writing any code:

1. Check that the tools this project needs are installed: Python 3.12 or newer, Node 20 or newer, git, and the GitHub CLI signed in. Tell me what is missing instead of installing system tools without asking.
2. Check `.env`. Do not print any values. `SEC_USER_AGENT` is needed right away, so if it is empty, ask me for the name and contact email to use and write it in. `FINNHUB_API_KEY`, `ALPACA_KEY_ID`, and `ALPACA_SECRET_KEY` are only needed from Phase 2. If they are empty, carry on with Phase 0 and Phase 1, then stop and remind me to add them before Phase 2.
3. Give me a short plan for Phase 0, Phase 1, and Phase 2, including anything in the spec you think is wrong, risky, or unclear.

Once I approve the plan, build Phase 0, then Phase 1, then Phase 2 from the "Build phases" table, in order. After each phase, run its "Done when" check, show me the result, and wait for my go-ahead before the next one.

Notes for these three phases:

- Ask me before creating the public GitHub repo and before the first push.
- In Phase 1, confirm the EDGAR `User-Agent` works with one request before starting the 500-company load, and show me the per-metric coverage report when it finishes.
- In Phase 2, make one test call to Finnhub and one to Alpaca first and tell me what the free keys can and cannot do. If Finnhub's real rate limit is not 60 per minute, set the config to what you find.
- In Phase 2, the Lynch panel, range bars, and sector medians come later. Leave clearly marked empty placeholders for them so the layout already matches the mockup.
- When the stock page is up, open it in a browser, compare it against `design/stock-page.dc.html`, and fix the differences you can see before showing me.

Stop after Phase 2 so I can use it and decide what to change.
