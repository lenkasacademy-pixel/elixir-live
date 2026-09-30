"""Derive the live page from the hand-refreshed Creative Ledger.

Keeps every renderer; swaps the baked arrays for data.json, makes the stamp live,
replaces the date-bound footer, and adds a Balance tab to the rail.
Usage: python3 make_live.py <ledger index.html> <out index.html>
"""
import re
import sys

src, out = sys.argv[1], sys.argv[2]
s = open(src).read()


def sub(old, new, count=1, regex=False):
    global s
    n = len(re.findall(old, s, flags=re.S)) if regex else s.count(old)
    assert n == count, f"expected {count} of {old[:70]!r}, found {n}"
    s = re.sub(old, lambda m: new, s, flags=re.S) if regex else s.replace(old, new)


# ---- head -----------------------------------------------------------------
sub(r"<!-- Standalone snapshot:.*?-->",
    "<!-- Live version: figures load from data.json, refreshed from Meta every few minutes by a GitHub Action. -->",
    regex=True)
sub(r"<title>.*?</title>", "<title>Elixir Live Ledger</title>", regex=True)

# ---- masthead + footer -----------------------------------------------------
sub('<h1>Creative <em>Ledger</em></h1>', '<h1>Creative <em>Ledger</em> &middot; live</h1>')
sub(r'<div class="stamp"><span class="dot"></span><span>Lifetime to .*?</span></div>',
    '<div class="stamp" id="stamp"><span class="dot off"></span><span>Loading from Meta&hellip;</span></div>',
    regex=True)
sub(r"<footer>.*?</footer>", """<footer>
    <span>Meta Ads, account 1358051173168970, pulled straight from Meta every few minutes and re-read by this page every minute. Figures are lifetime unless a table says otherwise. Today is a part-day: Meta keeps revising the latest two days as late installs land, so today stays out of every window total. Reach is de-duplicated by Meta and never adds up across days, campaigns or age bands, so totals leave it blank on purpose. Two ads had their creative swapped on 22 September; each is split here, with the retired creative carrying everything to 21 September. Written commentary on what moved and why lives in the daily <a href="https://lenkasacademy-pixel.github.io/elixir-reports/">Creative Ledger</a>.</span>
    <span>GST shown at 18% of media spend.</span>
  </footer>""", regex=True)

# ---- data: from data.json instead of baked arrays -------------------------
sub(r"/\* =+\n   Snapshot data .*?=+ \*/\n", """/* ============================================================
   Live data - data.json, written by fetch.py from the Meta Marketing API
   and force-pushed to the `data` branch by the refresh workflow.
   ============================================================ */
""", regex=True)
sub(r'const SNAP_DAY = "[^"]*";\n', 'let SNAP_DAY = "", GENERATED = "", BAL = null;\n', regex=True)
for name in ("CID", "CAMP ", "ADS  ", "DAILY", "AGE  ", "ANAME", "ADAY"):
    sub(r"const %s ?= \[.*?\];\n" % re.escape(name), "", regex=True)
sub('const YEAR  = "2026-";\n', 'let CID = [], CAMP = [], ADS = [], DAILY = [], AGE = [], ANAME = [], ADAY = [], YEAR = "2026-";\n')

sub('when this was taken" : "the last day in this report"',
    'at the last refresh" : "the last day in this report"')

# ---- Balance tab -----------------------------------------------------------
sub('''  if (state.tab !== "all" && !allCampaigns().some(c => c.id === state.tab)) state.tab = "all";''',
    '''  if (state.tab !== "all" && state.tab !== "balance" && !allCampaigns().some(c => c.id === state.tab)) state.tab = "all";''')
sub('''  rail.innerHTML = `<div class="rail-h">Campaigns</div>` + all + list.map''',
    '''  const b = BAL, warn = balanceLevel();
  const bal = `<div class="rail-h">Account</div>
    <button type="button" class="tab" data-tab="balance" aria-pressed="${state.tab === "balance"}">
      <span class="t">Balance</span>
      <span class="s">${b && b.capLeft != null ? `<span class="pill ${warn === "crit" ? "bad" : warn === "warn" ? "iss" : "live"}">${esc(inr(b.capLeft))} left</span> before the limit` : "spending limit &amp; top-ups"}</span>
    </button>`;
  rail.innerHTML = bal + `<div class="rail-h">Campaigns</div>` + all + list.map''')
sub('''  host.innerHTML = state.tab === "all" ? sheetAll() : sheetCampaign(state.tab);''',
    '''  host.innerHTML = state.tab === "balance" ? sheetBalance()
    : state.tab === "all" ? sheetAll() : sheetCampaign(state.tab);''')

BALANCE_JS = r'''
/* ============================================================
   Balance - spending limit, prepaid top-ups, charges, today by hour
   ============================================================ */
const istTime = t => new Date(t.replace("+0000", "Z")).toLocaleString("en-IN",
  { timeZone:"Asia/Kolkata", day:"numeric", month:"short", hour:"numeric", minute:"2-digit" });

/* Average spend over the last three settled days, all campaigns. */
function recentPace(){
  const days = dailyRollupAll().filter(d => d.date !== SNAP_DAY).slice(0, 3);
  return days.length ? { avg: sum(days, d => d.spend) / days.length, n: days.length } : null;
}
function dailyRollupAll(){
  const by = new Map();
  (rowsOf("daily") || []).map(normalise).forEach(r => by.set(r.date, (by.get(r.date) || 0) + r.spend));
  return [...by].map(([date, spend]) => ({ date, spend })).sort((a, b) => a.date < b.date ? 1 : -1);
}
/* "crit" under two days of budget left before the limit, "warn" under five. */
function balanceLevel(){
  const b = BAL;
  if (!b || b.capLeft == null) return "";
  const perDay = Math.max(b.dailyBudget || 0, recentPace()?.avg || 0) || 1;
  const days = b.capLeft / perDay;
  return days < 2 ? "crit" : days < 5 ? "warn" : "";
}

function sheetBalance(){
  const b = BAL;
  if (!b) return `<div class="state"><div class="p">Balance has not loaded yet.</div></div>`;
  const pace = recentPace(), level = balanceLevel();
  const daysAt = per => per > 0 && b.capLeft != null ? (b.capLeft / per).toFixed(1) : "—";
  const usedPct = b.spendCap ? Math.min(100, b.amountSpent / b.spendCap * 100) : 0;
  const today = sum(b.hourlyToday, h => h.spend);

  const alert = level ? `<div class="bal-alert ${level}">${level === "crit"
      ? "<strong>The spending limit is about to stop every ad.</strong> "
      : "<strong>The spending limit is getting close.</strong> "}
      At the current pace the account reaches it in about ${esc(daysAt(Math.max(b.dailyBudget, pace?.avg || 0)))} days.
      When it does, Meta stops delivery on every campaign until the limit is raised in
      Ads Manager &rarr; Billing &rarr; Payment settings &rarr; Account spending limit.</div>` : "";

  const status = { 1:"Active", 2:"Disabled", 3:"Unsettled", 7:"Pending risk review", 9:"In grace period", 101:"Closed" }[b.status] || ("Status " + b.status);

  const cap = `<section class="band">
    <div class="band-top">
      <div class="invoice">
        <div class="k">Left before the account spending limit</div>
        <div class="v">${esc(b.capLeft == null ? "No limit set" : inr2(b.capLeft))}</div>
      </div>
      <div><div class="k">Spending limit</div><div class="v">${esc(b.spendCap == null ? "—" : inr2(b.spendCap))}</div></div>
      <div><div class="k">Spent against it</div><div class="v">${esc(inr2(b.amountSpent))}<small>${usedPct.toFixed(1)}%</small></div></div>
    </div>
    <div class="meter" role="img" aria-label="${usedPct.toFixed(1)}% of the spending limit used"><i class="${level}" style="width:${usedPct}%"></i></div>
    <div class="band-btm">
      <div><div class="k">Days left at budget</div><div class="v">${esc(daysAt(b.dailyBudget))}<small>${esc(inr(b.dailyBudget))}/day</small></div></div>
      <div><div class="k">Days left at recent pace</div><div class="v">${esc(pace ? daysAt(pace.avg) : "—")}<small>${pace ? esc(inr(pace.avg)) + "/day, last " + pace.n + " days" : ""}</small></div></div>
      <div><div class="k">Spent today so far</div><div class="v">${esc(inr2(today))}</div></div>
      <div><div class="k">Account</div><div class="v">${esc(status)}<small>${b.prepay ? "prepaid" : "postpaid"}</small></div></div>
    </div></section>`;

  const last = b.topups[0];
  const since = last ? b.charges.filter(c => c.t > last.t) : [];
  const usedSince = sum(since, c => c.amount) + (b.unbilled || 0);
  const prepaid = last ? card("Prepaid funds", "money added by UPI, drawn down by Meta's daily charge", `
      <div class="band-btm bal-3">
        <div><div class="k">Last top-up</div><div class="v">${esc(inr(last.amount))}<small>${esc(istTime(last.t))}</small></div></div>
        <div><div class="k">Used since</div><div class="v">${esc(inr2(usedSince))}<small>${since.length} charge${since.length === 1 ? "" : "s"} + ${esc(inr2(b.unbilled || 0))} not yet charged</small></div></div>
        <div><div class="k">Top-ups, last 60 days</div><div class="v">${esc(inr(sum(b.topups, t => t.amount)))}<small>${b.topups.length} payments</small></div></div>
      </div>`,
      `Meta does not give this token the exact prepaid balance: it sits behind a finance permission the
       system user does not have. What is shown is everything this token can see &mdash; the last top-up and
       what has been charged since. The first charge after a top-up can cover spend from before it, so
       <em>used since</em> leans high. The spending limit above is exact and is the one that stops the ads
       outright. If spend stalls for hours while budget is left, check both.`) : "";

  const topups = card("Money added", "last 60 days, newest first", table([
    { label:"When (IST)", num:false, cell:r => esc(istTime(r.t)), sortVal:r => Date.parse(r.t.replace("+0000","Z")) },
    { label:"Amount", cell:r => esc(inr2(r.amount)), sortVal:r => r.amount },
    { label:"Via", num:false, cell:r => esc(r.via || "—") }
  ], b.topups, { total:(c, i) => i === 0 ? "Total" : c.label === "Amount" ? esc(inr2(sum(b.topups, t => t.amount))) : "" }));

  const charges = card("Daily charges", "what Meta took from the balance, newest first", table([
    { label:"Charged (IST)", num:false, cell:r => esc(istTime(r.t)), sortVal:r => Date.parse(r.t.replace("+0000","Z")) },
    { label:"Amount", cell:r => esc(inr2(r.amount)), sortVal:r => r.amount }
  ], b.charges.slice(0, 21), { total:(c, i) => i === 0 ? "Last " + Math.min(21, b.charges.length) : c.label === "Amount" ? esc(inr2(sum(b.charges.slice(0, 21), x => x.amount))) : "" }),
    "Each charge covers roughly the previous day's spend.");

  const hi = Math.max(1, ...b.hourlyToday.map(h => h.spend));
  const hours = card("Today by the hour", "a run of near-empty hours with budget left usually means the balance or the limit ran dry",
    b.hourlyToday.length ? `<div class="hours">${b.hourlyToday.map(h => `
      <div class="hr" title="${h.hour}:00 &mdash; ${esc(inr2(h.spend))}"><i style="height:${Math.max(2, h.spend / hi * 100)}%"></i><span>${h.hour}</span></div>`).join("")}</div>`
      : `<div class="state"><div class="p">No spend yet today.</div></div>`);

  return alert + cap + `<div class="bal-grid">${prepaid}${hours}</div>` + `<div class="bal-grid">${topups}${charges}</div>`;
}
'''
sub('''/* ============================================================
   Events
   ============================================================ */''', BALANCE_JS + '''
/* ============================================================
   Events
   ============================================================ */''')

# ---- boot: load, then re-read every minute ---------------------------------
sub(r'''/\* =+\n   Boot — everything is already here\n   =+ \*/\nstate\.data = \{.*?\};\nautoTab\(\);\npaint\(\);\n''', r'''/* ============================================================
   Boot - load data.json, then re-read it every minute
   ============================================================ */
const DATA_URL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) ? "data.json"
  : "https://raw.githubusercontent.com/lenkasacademy-pixel/elixir-live/data/data.json";

function stamp(){
  const el = $("#stamp");
  if (!GENERATED){ return; }
  const at = Date.parse(GENERATED), mins = (Date.now() - at) / 60000;
  const cls = mins > 60 ? "off" : mins > 20 ? "stale" : "";
  const when = new Date(at).toLocaleString("en-IN", { timeZone:"Asia/Kolkata", day:"numeric", month:"short", hour:"numeric", minute:"2-digit" });
  el.innerHTML = `<span class="dot ${cls}"></span><span>Live &middot; pulled from Meta ${esc(ago(at))} (${esc(when)} IST)${mins > 60 ? " &mdash; refresh has stalled" : ""}</span>`
    + `<button type="button" class="refresh" id="reload" title="Meta is pulled every 5 minutes; this loads the latest pull now">${esc(reloadLabel)}</button>`;
}
let reloadLabel = "Refresh";

function load(d){
  ({ SNAP_DAY, CID, CAMP, ADS, DAILY, AGE, ANAME, ADAY, YEAR } = d);
  GENERATED = d.generated; BAL = d.BALANCE;
  state.data = {
    campaigns: { rows: CAMP.map(hCamp),  more:false },
    ads:       { rows: ADS.map(hAd),     more:false },
    daily:     { rows: DAILY.map(hDay),  more:false },
    age:       { rows: AGE.map(hAge),    more:false },
    adDaily:   { rows: ADAY.map(hAdDay), more:false }
  };
  autoTab();
  paint();
}

async function pull(){
  try {
    const r = await fetch(DATA_URL + "?t=" + Date.now(), { cache:"no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.generated !== GENERATED) load(d);
  } catch (e) {
    if (!GENERATED) $("#band").innerHTML = `<div class="state"><div class="h err">Could not load the live figures</div>
      <div class="p">${esc(e.message)}. The page tries again every minute; the daily
      <a href="https://lenkasacademy-pixel.github.io/elixir-reports/">Creative Ledger</a> has yesterday's snapshot.</div></div>`;
  }
  stamp();
}
pull();
setInterval(pull, 60000);

/* Manual refresh: re-reads the latest pull now. It cannot make Meta pull sooner -
   that would need a GitHub key in this public page - but pulls land every 5 minutes. */
document.addEventListener("click", async e => {
  const b = e.target.closest("#reload");
  if (!b || b.disabled) return;
  const before = GENERATED;
  b.disabled = true; b.textContent = "Refreshing…";
  await pull();
  reloadLabel = GENERATED !== before ? "Updated" : "Up to date";
  stamp();
  setTimeout(() => { reloadLabel = "Refresh"; stamp(); }, 2500);
});
''', regex=True)

# ---- styles for the balance tab --------------------------------------------
sub('''  if (queued) return;
  queued = true;''', '''  if (document.hidden){ renderScope(); renderBand(); renderLatest(); renderRail(); renderSheet(); return; }
  if (queued) return;
  queued = true;''')

sub("</style>", """
/* ---------- balance ---------- */
.bal-alert{margin:24px 0 0; padding:14px 18px; border-radius:12px; font-size:13.5px; line-height:1.5}
.bal-alert.warn{background:var(--warn-bg); color:var(--warn)}
.bal-alert.crit{background:var(--crit-bg); color:var(--crit)}
.sheet > .band:first-child{margin-top:0}
.meter{height:6px; background:var(--sunk)}
.meter i{display:block; height:100%; background:var(--accent)}
.meter i.warn{background:var(--warn)} .meter i.crit{background:var(--crit)}
.bal-grid{display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; margin-top:18px}
.bal-3{grid-template-columns:repeat(3,1fr)}
.bal-3 > div{padding:14px 16px}
.bal-3 .v{font-size:17px}
.bal-3 .v small{display:block; margin:4px 0 0; font-size:11.5px; line-height:1.4}
.bal-grid table{min-width:0}
.hours{display:flex; align-items:flex-end; gap:3px; height:130px; padding:14px 18px 8px}
.hours .hr{flex:1; height:100%; display:flex; flex-direction:column; justify-content:flex-end; align-items:center; gap:4px}
.hours .hr i{display:block; width:100%; background:var(--accent); border-radius:2px 2px 0 0}
.hours .hr span{font:10px "IBM Plex Mono",monospace; color:var(--ink-3)}
@media (max-width:900px){ .bal-grid, .bal-3{grid-template-columns:1fr} }
</style>""")

open(out, "w").write(s)
print("wrote", out, len(s), "bytes")
