# Elixir Social · Live Creative Ledger

Live at https://lenkasacademy-pixel.github.io/elixir-live/

The same Creative Ledger as [elixir-reports](https://github.com/lenkasacademy-pixel/elixir-reports)
(campaign rail, per-ad tables, day-by-day, age bands, the 10-day table), but fed live from Meta,
plus a **Balance** tab: the account spending limit and what is left of it, days left at budget and
at recent pace, prepaid top-ups, daily charges, and today's spend by the hour.

- `fetch.py` pulls ad account 1358051173168970 from the Meta Marketing API and writes `data.json`
  in exactly the ledger's array shapes (`CID`, `CAMP`, `ADS`, `DAILY`, `AGE`, `ANAME`, `ADAY`) plus `BALANCE`.
- `.github/workflows/refresh.yml` runs it every 5 minutes (GitHub's schedule is best-effort, so
  gaps of 5–15 minutes are normal) and force-pushes `data.json` alone to the `data` branch.
- `index.html` (served by Pages from `main`) re-reads that file every minute. The stamp dot goes
  amber after 20 minutes without new data and grey after 60.

`index.html` is generated from the snapshot ledger's page by `make_live.py`-style edits: same
renderers, data loaded from JSON, date-bound footer prose removed. Commentary stays in the snapshot ledger.

**Append-only lists in `fetch.py`:** `CID` and `ANAME` map indexes that every row carries. Never
reorder them. A new campaign is appended automatically once it spends. `SPLITS` holds the two ads
whose creative was replaced on 22 Sep 2026; the retired creative keeps everything to 21 Sep.

**Balance limits:** the token cannot read the exact prepaid balance (`funding_source_details`
needs a finance permission the system user lacks). The page shows the last top-up and what has
been charged since, from the account activity log. The spending limit (`spend_cap − amount_spent`)
is exact, and it is what stops every ad when it runs out.

The Meta token is the `META_TOKEN` repository secret (System User "elixirads", app "elixir").
It never appears in the page or in `data.json`. To rotate it: Settings → Secrets and variables →
Actions → META_TOKEN → Update, then Actions → Refresh ad data → Run workflow.

Run locally: `META_TOKEN=... python3 fetch.py && python3 -m http.server` (on localhost the page
reads `data.json` next to it instead of the data branch).
