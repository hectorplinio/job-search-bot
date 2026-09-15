# Job Search Bot

[![CI](https://github.com/hectorplinio/job-search-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/hectorplinio/job-search-bot/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Searches nine job boards, scores every posting against your profile and sends
only the ones worth your time to Telegram. Hand it the link to a posting and it
writes you a tailored cover letter and CV summary.

It ships configured for a backend profile (Python, Node/TypeScript,
microservices, hexagonal architecture), but it works for any profile: all the
criteria live in `config.yaml` and `profile/cv.yaml`, so changing them touches
no code. There is a complete second profile in
[`examples/frontend/`](examples/frontend/), and the instructions are in
[Using it with your own profile](#using-it-with-your-own-profile).

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux/macOS: source .venv/bin/activate
pip install -e .

copy .env.example .env          # on Linux/macOS: cp .env.example .env
```

Fill in `.env` with three things:

| Variable | Where it comes from |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The token BotFather gives you (see below) |
| `TELEGRAM_CHAT_ID` | Your chat, via `jobbot chat-id` (see below) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |

### Creating the Telegram bot

It takes two minutes and needs no other sign-up.

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**, the
   official account that creates bots. It has a verified badge.
2. Send it `/newbot`.
3. It asks for a **name** (what you will see in your chat list, for example
   `My job alerts`) and then a **username**, which must end in `bot` and be
   unique, for example `ada_job_alerts_bot`.
4. It replies with a token that looks like `8123456789:AAH...`. Copy it into
   `TELEGRAM_BOT_TOKEN` in `.env`. **That token is a password**: whoever holds
   it controls the bot. Never commit it to a repository.
5. Search for your bot by the username you chose, open the chat and press
   **Start**. This step is required: Telegram does not let a bot write first.
6. Send it anything, say `hello`, and run:

   ```bash
   jobbot chat-id
   ```

   It prints your chat id. Copy it into `TELEGRAM_CHAT_ID`.

If `jobbot chat-id` finds nothing, the bot has no unread messages: write to it
again and repeat. And if you already have the bot running with `jobbot bot`,
stop it first, because the listening process takes the messages.

Try it without spending or sending anything:

```bash
jobbot run --dry-run --no-llm
```

When you like what you see on screen:

```bash
jobbot run
```

---

## Commands

```
jobbot run                    one pass: search, filter, score and alert
jobbot run --dry-run          the same, but sends nothing to Telegram
jobbot run --no-llm           rule-based scoring only, spends nothing on the API
jobbot bot                    starts the bot so you can talk to it
jobbot apply <url>            cover letter + summary for one posting
jobbot apply <url> -o out/    and saves them to files as well
jobbot stats                  what the bot has seen
jobbot usage                  how much you have spent on the Claude API
jobbot sources                which sources are enabled
jobbot check-sources          tries every source and reports how many it returns
jobbot login [board]          renews a job board session with your account
jobbot cookies                the state of the stored sessions
jobbot chat-id                your Telegram chat id
```

In Telegram, with `jobbot bot` running:

```
/buscar          runs a search now
/top             the best postings still pending
/oferta <url>    cover letter + summary
/carta <url>     cover letter only
/summary <url>   CV summary only
/stats           history
/usage           spend on the Claude API
/proxima         when the next search is due
```

You can also paste it a bare link, or the text of a posting when the board
demands a login. Every alert carries two buttons, **Cover letter** and
**Summary**, which write the documents without you copying the URL.

---

## The sources

Tested against the real job boards in September 2026.

| Source | How it gets in | State |
|---|---|---|
| Company boards | Greenhouse and Ashby, JSON with no key | **The best**: the posting shows up here before anywhere else |
| Manfred | Public JSON API | Very good: salary and remote percentage in the listing |
| LinkedIn | Guest endpoint, no login | Works, but its ranking hides postings |
| Tecnoempleo | Search page HTML | Works |
| InfoJobs | Search page HTML | Works on and off: blocks by IP and is slow to release |
| RemoteOK | Public JSON API | Works; international postings in USD |
| We Work Remotely | RSS | Works |
| Remotive | Public JSON API | **Off**: its free feed is 16 postings, all from one agency |
| Himalayas | Public JSON API | US companies; it pages, but 9 out of 10 are US only |
| Otta | Browser with your session | Works: walks your matches one at a time |
| Glassdoor | Search page HTML | **Off**: 403 by IP after a few requests |

Otta is the only one that needs an account: Playwright plus `jobbot login otta`.
The others work without registering anywhere.

**How to reach foreign companies without leaving Spain.** Not by widening
LinkedIn's locations. Measured: searching in the United Kingdom, Ireland or the
United States, 0 out of 30 results were open to someone in Spain, because their
filter is about where the role *is*, not who may apply.

What does work is reading the companies' own job boards. Grafana Labs publishes
the same role per country, so the Spanish version that no aggregator shows you
appears right there:

```
Grafana Labs   125 postings on its board  ->  8 for Spain
Affirm         203 postings               -> 19 for Spain
Monzo           69 postings               ->  8 across Barcelona and Madrid
```

Companies are configured in `sources.companies.watchlist`. To add one, look at
the URL of its careers page: `job-boards.greenhouse.io/COMPANY` means
`ats: greenhouse`, and `jobs.ashbyhq.com/COMPANY` means `ats: ashby`.

**About United States postings.** Remotive and Himalayas publish which countries
they accept candidates from, so the bot drops the ones you cannot take before
scoring them. The proportion measured on a real run:

```
120 postings reviewed on Himalayas -> 110 United States only -> 2 eligible
```

That is not a filter bug, it is the state of the market. A United States
company needs an Employer of Record to hire in Spain, and most have not set one
up.

**What LinkedIn will not give you.** Its guest endpoint serves 10 results per
request, so the bot pages to collect more. Even so, its ranking for generic
searches leaves postings out of reach: a specific posting was verified not to
appear in the first 100 results for `backend engineer python`, while it came up
first when searching by the company name. No amount of paging fixes that. A
search engine is a funnel, not a guarantee.

A source that fails returns zero and the rest carry on: it never sinks the run.
The summary of each pass tells you how many each one brought, so a broken
source is visible immediately.

---

## Using your own accounts

Four job boards behave differently when you are signed in. What each one gains
and what you risk:

| Board | What your account gains | Recommendation |
|---|---|---|
| InfoJobs | It stops blocking you by IP | Yes |
| Glassdoor | It stops answering 403 | Yes |
| Otta | It is the only way: the listing is behind sign-up | Yes, with a browser |
| LinkedIn | Practically nothing | **No** |

### Why not LinkedIn

The guest endpoint already returns the same results without authenticating.
Adding your session improves nothing noticeable and does change who pays if
something goes wrong: a block on an anonymous IP costs you nothing, an account
restriction leaves you without a profile exactly while you are job hunting.
LinkedIn is among the most aggressive about automated access. The code accepts
`LINKEDIN_COOKIE` because it is your call, but it warns on every run and
`jobbot login linkedin` asks before going ahead.

### How sessions are renewed

Cookies expire. Copying them from the browser by hand every week is no way to
live, and logging in with a username and password over plain HTTP does not
work: all four boards protect their login too, with captchas, with client
fingerprinting or, in Otta's case, with an AWS WAF challenge that requires
executing JavaScript.

What does work is a real browser with a persistent profile:

```bash
pip install -e ".[browser]"
playwright install chromium

jobbot login              # opens one window per board
jobbot login infojobs     # or just one
jobbot login infojobs --auto   # fills the form with what is in .env
```

The first time you sign in yourself in the window, with your 2FA and your
captcha if it asks. The profile stays in `data/browser-profile/` and keeps the
session for weeks, so from then on repeating the command is enough: it no
longer asks for a password. The cookies are stored in `data/cookies.json` with
their expiry date, and they win over anything you paste by hand into `.env`.

```bash
jobbot cookies         # which sessions exist and how long they have left
jobbot check-sources   # tries every source and reports how many it returns
```

`jobbot cookies` never prints the value of a cookie, only its state.

If you would rather not keep passwords in a file, leave `*_USER` and
`*_PASSWORD` empty and use `jobbot login` without `--auto`. It works the same,
you just sign in yourself.

### Where all of this is stored

`data/` holds the history, the cookies and the browser profile with your
accounts signed in. Copying that folder is the same as copying your sessions:
whoever has it gets in with no password and no second factor. The whole folder
is in `.gitignore`.

The practical consequence for scheduling: **the sources that need a session do
not work well on GitHub Actions**. The runner comes out of a data-centre IP,
which does trigger email verification, and the browser profile does not survive
between runs. Two sensible options:

- Leave only what needs no account on Actions, which is most of it: Manfred,
  guest LinkedIn, Tecnoempleo, RemoteOK and We Work Remotely.
- Or run everything on your own machine, which is where your sessions count.

### About InfoJobs

It returned postings on the first pass and stopped after a few searches in a
row: it serves a 29 KB page with no cards instead of a 403, and it takes a good
while to release the IP. The parser is tested against its real HTML, so when it
answers, it works.

Mitigations already in place: only two broad queries (`python`, `backend`)
instead of the six general ones, and 1.5 s between requests to the same domain.
From a normal home IP, with the bot running every 4 hours, it should be fine;
if you keep seeing `infojobs 0`, raise the interval or leave it a single query.

### About Glassdoor

The parser works and is tested, but Glassdoor returns 403 after a few requests
from the same IP. It is in `config.yaml` with `enabled: false`. Turn it on if
you come out of a different IP or if you do not mind it failing often.

### About Otta

Otta is now Welcome to the Jungle, and it has two barriers on top:

```
x-amzn-waf-action: challenge
```

An AWS WAF challenge that is only passed by executing JavaScript, and a listing
that sits behind sign-up: the "find a job" button leads to
`/en/get-started/job-title`, not to results.

That is why copying the cookie by hand is no use here. Measured: the WAF token
that accompanies the session expired in little over an hour. What does work is
browser mode, which solves the challenge on its own and keeps the session
alive:

```bash
pip install -e ".[browser]"
playwright install chromium
jobbot login otta
# and in config.yaml: sources.otta.enabled: true
```

**An important warning about Otta.** Its next button is not a "show me the next
posting": it marks the current one as seen and removes it from your matches.
The bot browses with your session, so it consumes your queue exactly as if you
had walked it yourself. The postings reach you on Telegram with their link, but
you will not see them again when you open Otta.

It is the only source with this effect; the others only read. If you would
rather review Otta by hand, lower `sources.otta.max_jobs` to 5 so a queue is
left, or set it to `enabled: false`.

Verified that the browser gets in and returns 598 KB of real content where
`httpx` received a 2 KB page. What has **not** been verified is parsing the
signed-in listing, because that needs your account. If `check-sources` gives
you 0 on Otta, the listing will be at a different path: set it in
`sources.otta.search_url`.

There is also an Algolia mode, pointing at the search their own site uses
(`algolia_app_id` and `algolia_api_key` in `config.yaml`), but those keys rotate
and have to be renewed by hand. RemoteOK and We Work Remotely cover the same
international-remote gap with no maintenance at all.

---

## How it decides what to send you

Four filters in order, cheapest first:

1. **Hard filters** (`config.yaml`, the `exclude` section). They drop a posting
   with no argument: junior or intern in the title, on-site required, salary
   below the minimum, an expired posting, no technology from the profile, or a
   title from another field (`Senior .NET Full-stack`, `React Native
   Developer`) that does not also name Python, Node or backend.

2. **Deduplication**. The same posting on LinkedIn and on InfoJobs collapses
   into one: the fingerprint normalises company and role, stripping corporate
   suffixes, cities and work-mode tags. A second fingerprint by canonical URL
   catches reposts.

3. **Rule-based scoring**, over 100 points split like this:

   | Block | Weight |
   |---|---|
   | Matching stack | 45 |
   | Salary | 25 |
   | Work mode | 20 |
   | Seniority | 10 |

   The result is mapped to a score from 1 to 10. It is a pure function, with no
   network and no state: same posting, same score.

   The bot also reads how many people have already applied, when the source
   publishes it. LinkedIn shows it on the posting. Being among the first adds
   points and a queue of two hundred subtracts, because the same posting is not
   worth the same with 6 candidates as with 200. If you want the equivalent of
   the "fewer than 10 applicants" filter, put a number in
   `exclude.max_applicants`; it ships empty because only LinkedIn reports it and
   a cap would penalise every other source.

4. **A second opinion from Claude**, only for the ones that already passed the
   cut. It returns the final score and the "why it fits" line you see in
   Telegram. It goes in batches of six postings per call, with a per-run cap in
   `scoring.llm_max_offers_per_run`.

The salary floor and target ship as example values in `config.yaml` and are
overridden from `.env` (see [Tuning the criteria](#tuning-the-criteria)). Below
the floor a posting is dropped; from the target up, the salary block scores
full marks. Postings with no published salary are accepted but score lower,
because otherwise you would be left with almost nothing.

---

## Cost

The scraping and the rule-based scoring are free. The only thing that costs
money is Claude, used in two places:

- **Scoring** the postings that passed the cut, in batches of six. With the
  caps in `config.yaml` that is 2 or 3 calls per run.
- **Writing** a cover letter and a summary, only when you ask for it.

With `claude-opus-5` at $5/M input and $25/M output, a run costs cents.
`jobbot run --no-llm` makes it zero.

There is no need to estimate it: the bot records every call and `jobbot usage`,
or `/usage` in Telegram, gives you today's spend, this month's and the total,
plus the split between scoring postings and writing applications. It stores the
amount as computed at call time, so a price change does not rewrite the past.

---

## Running it on a schedule

The bot handles that itself. While `jobbot bot` is listening, it launches a
search every 4 hours on its own. It is configured in `config.yaml`:

```yaml
schedule:
  enabled: true
  every_hours: 4
  first_run_after_minutes: 3
```

One single process, and that matters more than it looks: the buttons on the
alerts only respond while the bot is alive, so tying the searches to that same
process guarantees you never get an alert with dead buttons. `/proxima` tells
you when the next one is due.

On Windows, a shortcut in the Startup folder launches it when you turn the
computer on. The launcher restarts itself if the process dies.

The alternative was a scheduled task calling `jobbot run`. It works, but it is
two things to keep alive instead of one, and the `.bat` ends in `pause` so you
can read the summary when running it by hand, which leaves a window open on
every automatic trigger.

`.github/workflows/job-search.yml` exists but **with the cron disabled**, manual
trigger only. The reason is that two sources depend on your machine: Otta uses
the browser profile holding your session, which does not survive between runner
executions, and InfoJobs blocks data-centre IPs. If you want it on Actions
anyway, uncomment the `schedule`, add the three secrets
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`) and accept
losing those two sources.

The SQLite history travels in the runner cache. If it is lost, the first pass
repeats postings you have already seen once and then returns to normal.

---

## Structure

Hexagonal architecture, ports and adapters:

```
src/jobbot/
  domain/          pure rules: models, salary, fingerprint, scoring, profile
  ports.py         what the domain needs from outside
  adapters/
    sources/       one class per job board, all behind the same interface
    http.py        shared client with per-domain throttling and retries
    persistence.py history in SQLite
    telegram_notifier.py
    llm/           Claude: scoring and writing
    offer_reader.py  a bare URL -> a posting (manual mode)
  application/     use cases: search, write
  container.py     composition root
  bot.py           Telegram commands
  cli.py           command line
```

The domain imports nothing from `adapters`. The `domain` and `application`
tests run with no network.

---

## Development commands

They live in the `Makefile`, so CI runs exactly what you run:

```bash
make install-dev   # installs the bot and the tooling
make check         # lint + types + format + tests + config loading
make dry-run       # a search that sends nothing and spends nothing on the LLM
make bot           # starts the bot listening on Telegram
make help          # everything else
```

Windows does not ship `make`. Install it with `winget install GnuWin32.Make`,
or copy the recipe you need by hand.

---

## Tests

CI runs them on every push and every pull request, on Python 3.11 and 3.12,
alongside `ruff check`, `flake8`, `mypy` and `black --check`. No secrets are
needed: no test touches the network.

Black is the formatter of record. `ruff format` is not used: it disagrees with
Black on multiline literals, and two formatters end up rewriting each other's
code.

```bash
pip install -r requirements-dev.txt
pytest
```

111 tests, all offline. The parsers are tested against fixtures copied from
each board's real HTML, odd cases included: the InfoJobs salary split by HTML
comments, Tecnoempleo's run-together "Salario:35000 a 38000", and the legal
notice RemoteOK slips in as the first array item.

An honest warning: these tests validate the parsing logic, not that the board
still serves that HTML. When a board changes its markup the tests stay green
and the source returns zero. That is why the summary of each pass breaks the
numbers down by source.

### What is verified against the real services and what is not

Verified with live requests: the enabled sources, deduplication across boards,
the scoring and the SQLite history.

Not verified, because it needs credentials that are not committed: the calls to
the Claude API (`scoring.use_llm`, `jobbot apply`, `/carta`, `/summary`) and the
actual delivery of Telegram messages. The code is written against the Messages
API with structured outputs and against python-telegram-bot v21, and both paths
are covered by tests with doubles, but the first time you add the keys it is
worth trying `jobbot apply <url>` before leaving it on a schedule.

---

## Tuning the criteria

Almost everything is in `config.yaml`:

- `salary.minimum` and `salary.target`, if you change your mind about the
  floor. Careful: the values in the YAML are an example, because this file is
  published. Yours go in `.env`, as `JOBBOT_SALARY_MINIMUM` and
  `JOBBOT_SALARY_TARGET`, which override the YAML. The minimum is compared
  against the **top** of the band, so a posting of "35.000 - 53.000" gets in
  even when your floor is 40.000.
- `keywords.weighted`, to raise or lower the weight of a technology.
- `exclude.off_profile_titles`, when a kind of role you do not want slips in.
- `scoring.notify_threshold`, if you get too many or too few.
- `sources.<name>.queries`, to give a fragile board fewer searches.

And `profile/cv.yaml` holds what Claude sees when it writes: the current
summary, the experience with its highlights, and `emphasis_rules`, which decides
which company comes to the front depending on what the posting asks for. If you
update your CV, update that file too.

---

## Using it with your own profile

The bot is not tied to a backend profile. What defines "a good posting" lives
entirely in data files, and none of them touches code:

| File | What it decides |
|---|---|
| `config.yaml` | What is searched, what is dropped and how much each technology weighs |
| `profile/cv.yaml` | What Claude knows about you when scoring and writing |
| `.env` | What you do not want published, such as your salary figures |

Both files can point somewhere else through environment variables, so you can
keep several profiles without touching yours:

```bash
JOBBOT_CONFIG_PATH=examples/frontend/config.yaml JOBBOT_PROFILE_PATH=examples/frontend/cv.yaml jobbot run --dry-run
```

`examples/frontend/` holds a complete profile for a frontend developer, which
serves as a template and as proof that this works: with those two files, a
"Senior React Engineer" posting scores high and a "Backend Engineer Python" one
is rejected.

To adapt it to you:

1. **`config.yaml`**: change `search.queries` to the searches for your role,
   `keywords.required_any` to what a posting must mention, and
   `keywords.weighted` to your technologies with their weight. Under `exclude`,
   `off_profile_titles` are the roles from another field and `core_title_terms`
   are the words that rescue a mixed title.
2. **`profile/cv.yaml`**: your summary, your experience with its highlights, and
   two blocks that guide the writing:
   - `emphasis_rules`: which experience to highlight based on what the posting
     mentions.
   - `cover_letter_anchors`: `always` is the experience that appears nearly
     every time, and each `when` entry adds a rule of the form "if the posting
     touches these words, lean on this other one".
3. Try it with `jobbot run --dry-run --no-llm`, which sends nothing and spends
   nothing.

The prompts are built from that file, so the letters talk about your companies
and your stack, not someone else's.

---

## Contributing

`main` is protected: changes go through a pull request, and CI has to be green
before it can be merged.

```bash
git checkout -b my-change
make check
git push origin my-change
```

---

## License

MIT. See [LICENSE](LICENSE).
