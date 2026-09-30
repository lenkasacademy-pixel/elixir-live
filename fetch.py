"""Pull Elixir Social's Meta ads into data.json for the live Creative Ledger.

Runs every 5 minutes from .github/workflows/refresh.yml. Standard library only.
The token comes from the META_TOKEN environment variable (a repo secret) and is
never written to the output.

The arrays it writes have exactly the shapes of the hand-refreshed Creative Ledger
(lenkasacademy-pixel/elixir-reports), so the page code is shared between the two:

  CAMP  [campIdx, name, status, spend, impr, reach, clicks, ctr, cpm, installs, regs]
  ADS   [name, campIdx, status, spend, impr, reach, clicks, ctr, cpm, linkClicks, installs, regs]
  DAILY ["MM-DD", campIdx, spend, impr, reach, clicks, ctr, cpm, installs, regs]
  AGE   [age, campIdx, spend, impr, reach, clicks, ctr, cpm, installs, regs]
  ADAY  ["MM-DD", campIdx, anameIdx, spend, impr, clicks, installs, regs]

Installs and registrations are null (not 0) where Meta returns no such action.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from datetime import datetime, timedelta, timezone

API = "https://graph.facebook.com/v23.0"
ACCOUNT = "act_1358051173168970"
IST = timezone(timedelta(hours=5, minutes=30))
TOKEN = os.environ.get("META_TOKEN", "").strip()
YEAR = "2026-"

# Index -> campaign id. APPEND ONLY: every row carries the index, so reordering
# re-labels history. A campaign not listed here is appended once it spends.
CID = ["120249010423390482", "120248552059290482", "120248779042430482",
       "120249146323630482", "120249010386050482", "120249183882130482",
       "120248544185220482", "120249090597080482", "120249585873390482"]

# Index -> creative name for ADAY. APPEND ONLY, for the same reason.
ANAME = ["v5 - I am a med student", "v4 - Ecg", "Influencer - 11sep",
         "v2 - Female ( asking medicos how they study)",
         "v3 - Checking on your med student friend at 1am",
         "v1 - male ( asking medicos how they study)",
         "influencer direct video ad - Rheumatoid Arthritis", "influencer - hasaan"]

# Ads whose creative was replaced on the same ad id. Meta keeps one history per id,
# so the retired creative gets everything up to `until` and the new one the rest.
SPLITS = {
    "120249212142170482": {"until": "2026-09-21", "old": "v4 - Ecg"},
    "120249183882150482": {"until": "2026-09-21", "old": "v1 - male ( asking medicos how they study)"},
}
ADAY_FROM = "2026-08-30"  # ad-level day rows start here, for the campaigns still running

ALL_STATUSES = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "IN_PROCESS", "WITH_ISSUES",
                "CAMPAIGN_PAUSED", "ADSET_PAUSED", "DISAPPROVED", "PENDING_REVIEW",
                "PREAPPROVED", "PENDING_BILLING_INFO"]
BASE = "spend,impressions,reach,clicks,ctr,cpm,actions"


def _open(url):
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = json.load(e).get("error", {})
        sys.exit(f"Meta API error {err.get('code')}: {err.get('message')}")


def get(path, **params):
    params["access_token"] = TOKEN
    return _open(f"{API}/{path}?{urllib.parse.urlencode(params)}")


def get_all(path, **params):
    params.setdefault("limit", 500)
    out, page = [], get(path, **params)
    while True:
        out += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            return out
        page = _open(nxt)


def insights(level, **params):
    return get_all(f"{ACCOUNT}/insights", level=level, **params)


def act(row, kind):
    for a in row.get("actions") or []:
        if a["action_type"] == kind:
            return int(float(a["value"]))
    return None


def r2(v):
    """Round half-up like Ads Manager (Python's round() sends 0.625 to 0.62)."""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def core(r):
    """spend, impr, reach, clicks, ctr, cpm - in the ledger's column order.
    CTR and CPM are null on a row with no impressions, as in the ledger."""
    impr = int(r.get("impressions", 0))
    return [r2(r.get("spend", 0)), impr, int(r.get("reach", 0)), int(r.get("clicks", 0)),
            r2(r["ctr"]) if impr and "ctr" in r else None,
            r2(r["cpm"]) if impr and "cpm" in r else None]


def counts(r):
    """True when a row carries anything worth keeping - a zero-spend day can still
    book late installs or registrations from earlier clicks."""
    return bool(float(r.get("spend", 0)) or int(r.get("impressions", 0))
                or any(v is not None for v in results(r)))


def results(r):
    return [act(r, "omni_app_install"), act(r, "omni_complete_registration")]


def rng(since, until):
    return json.dumps({"since": since, "until": until})


def main():
    if not TOKEN:
        sys.exit("META_TOKEN is not set")
    now = datetime.now(IST)
    today = now.date().isoformat()
    lifetime = rng("2026-07-01", today)
    status_filter = json.dumps([{"field": "effective_status", "operator": "IN", "value": ALL_STATUSES}])

    # ---- campaigns ---------------------------------------------------------
    camps = {c["id"]: c for c in get_all(f"{ACCOUNT}/campaigns", filtering=status_filter,
                                         fields="id,name,effective_status,daily_budget")}
    life = {r["campaign_id"]: r for r in insights("campaign", time_range=lifetime,
                                                   fields="campaign_id,campaign_name," + BASE)}
    cid = list(CID)
    for c_id, r in sorted(life.items()):
        if c_id not in cid and float(r.get("spend", 0)) > 0:
            cid.append(c_id)
    idx = {c: i for i, c in enumerate(cid)}

    CAMP = []
    for i, c_id in enumerate(cid):
        r = life.get(c_id, {})
        meta = camps.get(c_id, {})
        CAMP.append([i, meta.get("name") or r.get("campaign_name", ""),
                     meta.get("effective_status", "DELETED"), *core(r), *results(r)])

    # ---- ads (lifetime, split where a creative was replaced) ---------------
    ad_meta = {a["id"]: a for a in get_all(f"{ACCOUNT}/ads", filtering=status_filter,
                                           fields="id,name,campaign_id,effective_status")}
    ad_fields = "ad_id,ad_name,campaign_id," + BASE
    ADS, seen = [], set()

    def ad_row(name, r, status, c_id):
        return [name, idx[c_id], status, *core(r), act(r, "link_click"), *results(r)]

    for r in insights("ad", time_range=lifetime, fields=ad_fields):
        a_id, c_id = r["ad_id"], r["campaign_id"]
        if c_id not in idx:
            continue
        seen.add(a_id)
        meta = ad_meta.get(a_id, {})
        status = meta.get("effective_status", "DELETED")
        if a_id in SPLITS:
            continue  # handled below from two windows
        ADS.append(ad_row(meta.get("name") or r["ad_name"], r, status, c_id))
    for a_id, sp in SPLITS.items():
        meta = ad_meta.get(a_id)
        if not meta:
            continue
        cut = (datetime.fromisoformat(sp["until"]) + timedelta(days=1)).date().isoformat()
        before = insights("ad", time_range=rng("2026-07-01", sp["until"]), fields=ad_fields,
                          filtering=json.dumps([{"field": "ad.id", "operator": "IN", "value": [a_id]}]))
        after = insights("ad", time_range=rng(cut, today), fields=ad_fields,
                         filtering=json.dumps([{"field": "ad.id", "operator": "IN", "value": [a_id]}]))
        ADS.append(ad_row(sp["old"], before[0] if before else {}, "REPLACED", meta["campaign_id"]))
        ADS.append(ad_row(meta["name"], after[0] if after else {}, meta["effective_status"], meta["campaign_id"]))
    # Ads that never delivered do not appear in insights at all.
    for a_id, meta in ad_meta.items():
        if (a_id not in seen and a_id not in SPLITS and meta["campaign_id"] in idx
                and meta["effective_status"] not in ("ARCHIVED", "DELETED")):
            ADS.append(ad_row(meta["name"], {}, meta["effective_status"], meta["campaign_id"]))
    ADS.sort(key=lambda row: -row[3])

    # ---- day rows and age bands -------------------------------------------
    DAILY = []
    for r in insights("campaign", time_range=lifetime, time_increment=1,
                      fields="campaign_id," + BASE):
        if r["campaign_id"] in idx and counts(r):
            DAILY.append([r["date_start"][5:], idx[r["campaign_id"]], *core(r), *results(r)])
    DAILY.sort(key=lambda row: (row[0], -row[2]))

    AGE = []
    for r in insights("campaign", time_range=lifetime, breakdowns="age",
                      fields="campaign_id," + BASE):
        if r["campaign_id"] in idx:
            AGE.append([r["age"], idx[r["campaign_id"]], *core(r), *results(r)])
    AGE.sort(key=lambda row: (row[1], row[0]))

    # ---- ad-level day rows for the campaigns still running ----------------
    live = [c for c in cid if camps.get(c, {}).get("effective_status") == "ACTIVE"]
    aname = list(ANAME)
    ADAY = []
    if live:
        for r in insights("ad", time_range=rng(ADAY_FROM, today), time_increment=1,
                          fields="ad_id,ad_name,campaign_id,spend,impressions,clicks,actions",
                          filtering=json.dumps([{"field": "campaign.id", "operator": "IN", "value": live}])):
            if not counts(r):
                continue
            a_id, day = r["ad_id"], r["date_start"]
            sp = SPLITS.get(a_id)
            name = sp["old"] if sp and day <= sp["until"] else ad_meta.get(a_id, {}).get("name", r["ad_name"])
            if name not in aname:
                aname.append(name)
            ADAY.append([day[5:], idx[r["campaign_id"]], aname.index(name),
                         r2(r.get("spend", 0)), int(r.get("impressions", 0)), int(r.get("clicks", 0)),
                         *results(r)])
    ADAY.sort(key=lambda row: (row[0], row[1], -row[3]))

    # ---- balance -----------------------------------------------------------
    acct = get(ACCOUNT, fields="name,account_status,disable_reason,currency,balance,amount_spent,"
                               "spend_cap,is_prepay_account,min_daily_budget")
    cap, spent = int(acct.get("spend_cap") or 0), int(acct.get("amount_spent") or 0)
    since = (now - timedelta(days=60)).date().isoformat()
    topups, charges, cap_changes = [], [], []
    for e in get_all(f"{ACCOUNT}/activities", since=since, limit=200,
                     fields="event_type,event_time,extra_data,actor_name"):
        try:
            x = json.loads(e.get("extra_data") or "{}")
        except ValueError:
            x = {}
        t = e["event_time"]
        if e["event_type"] == "funding_event_successful":
            topups.append({"t": t, "amount": int(x.get("amount", 0)) / 100, "via": x.get("network_id", "")})
        elif e["event_type"] == "ad_account_billing_charge":
            charges.append({"t": t, "amount": int(x.get("new_value", 0)) / 100})
        elif "spend_cap" in e["event_type"] or "spend_limit" in e["event_type"]:
            cap_changes.append({"t": t, "type": e["event_type"], "who": e.get("actor_name", ""),
                                "old": x.get("old_value"), "new": x.get("new_value")})
    hourly = [{"hour": int(r["hourly_stats_aggregated_by_advertiser_time_zone"][:2]),
               "spend": round(float(r.get("spend", 0)), 2)}
              for r in insights("account", time_range=rng(today, today),
                                breakdowns="hourly_stats_aggregated_by_advertiser_time_zone",
                                fields="spend")]
    balance = {
        "status": acct.get("account_status"), "disableReason": acct.get("disable_reason"),
        "prepay": bool(acct.get("is_prepay_account")),
        "unbilled": int(acct.get("balance") or 0) / 100,
        "spendCap": cap / 100 if cap else None, "amountSpent": spent / 100,
        "capLeft": (cap - spent) / 100 if cap else None,
        "dailyBudget": sum(int(camps[c].get("daily_budget") or 0) for c in live) / 100,
        "topups": sorted(topups, key=lambda e: e["t"], reverse=True),
        "charges": sorted(charges, key=lambda e: e["t"], reverse=True),
        "capChanges": cap_changes,
        "hourlyToday": sorted(hourly, key=lambda h: h["hour"]),
    }

    data = {
        "generated": now.isoformat(timespec="seconds"),
        "SNAP_DAY": today, "YEAR": YEAR,
        "CID": cid, "CAMP": CAMP, "ADS": ADS, "DAILY": DAILY, "AGE": AGE,
        "ANAME": aname, "ADAY": ADAY, "BALANCE": balance,
    }
    with open("data.json", "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"ok {now:%d %b %H:%M} IST: {len(CAMP)} campaigns, {len(ADS)} ad rows, "
          f"{len(DAILY)} day rows, {len(ADAY)} ad-day rows; cap left {balance['capLeft']}")


if __name__ == "__main__":
    main()
