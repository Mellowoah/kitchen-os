"""Dinner decision engine: ranks meals by waste reduction first, then fit with what's in the kitchen."""
from datetime import timedelta
from . import kb, model
from .meals import MEALS, BY_ID

VERIFY_NOTE = ("Ingredient checks use general food knowledge, not product labels. Always verify labels and "
               "packaging yourself - brands, 'may contain' warnings and cross-contact are things I can't see.")
URG = {"use_soon": 1.0, "use_week": 0.45, "low": 0.05}

def conf_word(c):
    return "fairly sure" if c >= 0.85 else "probably" if c >= 0.6 else "maybe" if c >= 0.35 else "not sure"

def pretty(key):
    return key[:1].upper() + key[1:]

def _pool(state, today):
    """Enriched, still-plausible items by key (best candidate per key)."""
    today = model.d(today)
    by = {}
    for it in state["items"]:
        e = model.enrich_item(it, today)
        if e["level"] <= 0.04 or e["conf_now"] < 0.25:
            continue
        if e["location"] != "freezer" and e["days_left"] < -1 and model._life(e["key"], e["location"]) <= 60:
            continue  # very likely gone off
        cur = by.get(e["key"])
        if not cur or e["conf_now"] * (1 + URG[e["tier"]]) > cur["conf_now"] * (1 + URG[cur["tier"]]):
            by[e["key"]] = e
    return by

def evaluate(meal, pool, members, use_up=None, allow_thaw=False):
    use_up = use_up or {}
    used, missing, unsure, thaw = [], [], [], []
    covered = 0
    for grp in meal["req"]:
        alts = [a for a in grp.split("|") if model.ok_for_all(members, a)]
        if not alts:
            return None
        cands = [pool[a] for a in alts if a in pool]
        best = max(cands, key=lambda e: e["conf_now"] * (1 + URG[e["tier"]] + (0.8 if e["key"] in use_up else 0)), default=None)
        if best and best["conf_now"] >= 0.35:
            f = kb.info(best["key"]) or {"flags": set()}
            if best["location"] == "freezer" and "slow" in f["flags"] and not allow_thaw:
                return None  # frozen solid: not a tonight meal (see the thaw nudge for tomorrow)
            covered += 1
            used.append(best)
            if best["conf_now"] < 0.6:
                unsure.append(best)
            if best["location"] == "freezer" and "slow" in f["flags"]:
                thaw.append(best)
        else:
            missing.append(alts[0])
    extras = []
    for o in meal["opt"]:
        if o in pool and pool[o]["conf_now"] >= 0.45 and model.ok_for_all(members, o):
            extras.append(pool[o])
    return dict(meal=meal, used=used, extras=extras, missing=missing, unsure=unsure, thaw=thaw, covered=covered, total=len(meal["req"]))

def score(c, members, today, history, use_up, season_cold, budget_day=None):
    m = c["meal"]
    today = model.d(today)
    waste = sum((URG[e["tier"]] + (0.8 if e["key"] in use_up else 0)) * e["conf_now"] for e in c["used"])
    waste += 0.3 * sum((URG[e["tier"]] + (0.8 if e["key"] in use_up else 0)) * e["conf_now"] for e in c["extras"])
    cov = c["covered"] / max(1, c["total"])
    s = 2.6 * waste + 3.0 * cov - 1.1 * len(c["missing"]) - 0.3 * len(c["thaw"])
    s += 1.6 * sum(1 for e in c["used"] + c["extras"] if e["key"] in use_up)  # an explicit 'use up X' wish
    weekday = today.weekday() < 5
    if weekday:
        s += 0.8 if m["mins"] <= 25 else 0.4 if m["mins"] <= 35 else -0.4 if m["mins"] > 45 else 0
    else:
        s += 0.2 if m["mins"] >= 35 else 0
    if any(x.get("kid") for x in members) and "kid" in m["tags"]:
        s += 0.5
    if m["season"]:
        s += 0.3 if (m["season"] == "cold") == season_cold else -0.3
    if "fallback" in m["tags"]:
        s -= 0.8
    cooked = [h for h in history if h["meal_id"] == m["id"] and h["action"] == "cooked"]
    rej = [h for h in history if h["meal_id"] == m["id"] and h["action"] == "rejected"]
    s += min(0.45, 0.15 * len(cooked))
    for h in cooked:
        age = (today - model.d(h["date"])).days
        s -= 3.0 if age <= 6 else 0.8 if age <= 14 else 0
    for h in rej:
        if (today - model.d(h["date"])).days <= 14:
            s -= 0.25
    if budget_day is not None:
        cost = sum((kb.info(k) or {"price": 3})["price"] for k in c["missing"])
        if cost > budget_day:
            s -= (cost - budget_day) / 5
    return round(s, 3)

def is_cold(today):
    return model.d(today).month in (10, 11, 12, 1, 2, 3)

def rank(state, today, dinner_only=True, allow_thaw=False, exclude=(), pool=None, budget_day=None, min_cov=0.6, max_missing=2, types=None, extra_hist=()):
    members = state["members"]
    pool = pool if pool is not None else _pool(state, today)
    use_up = state.get("use_up", {})
    hist = list(state["history"]) + list(extra_hist)
    out = []
    for m in MEALS:
        if m["id"] in exclude:
            continue
        if types and not (set(types) & set(m["types"])):
            continue
        if dinner_only and not types and "dinner" not in m["types"]:
            continue
        c = evaluate(m, pool, members, use_up, allow_thaw)
        if not c or c["covered"] == 0:
            continue
        if c["covered"] / c["total"] < min_cov or len(c["missing"]) > max_missing + len(c["thaw"]):
            continue
        c["score"] = score(c, members, today, hist, use_up, is_cold(today), budget_day)
        out.append(c)
    out.sort(key=lambda c: -c["score"])
    return out

# ----------------------------------------------------------- presentation

def describe_item(e, today=None):
    left = e["days_left"]
    n = pretty(e["name"])
    if e["location"] == "freezer":
        if e["tier"] == "low":
            return f"{n}: frozen, plenty of time left"
        return f"{n}: has been frozen a while, worth using in the next few weeks"
    if left <= 0:
        when = "at the edge, check it before using"
    elif left <= 1:
        when = "probably needs using within a day"
    elif left <= 3:
        when = f"probably about {left} days left"
    elif left < 14:
        when = f"roughly {left} days left"
    else:
        when = "plenty of time left"
    return f"{n}: {when} ({round(e['conf_now'] * 100)}% sure)"

def reasons_for(c, state, today):
    r = []
    urgent = sorted([e for e in c["used"] if e["tier"] != "low" or e["key"] in state.get("use_up", {})],
                    key=lambda e: (-URG[e["tier"]], -e["conf_now"]))
    for e in urgent[:2]:
        if e["key"] in state.get("use_up", {}):
            r.append(f"You asked to use up {e['name']}")
        else:
            r.append(describe_item(e))
    have = [pretty(e["name"]) for e in c["used"]]
    if have:
        n_have = c["covered"]
        r.append(f"Uses {n_have} of {c['total']} main ingredients you probably already have ({', '.join(have[:4])})")
    m = c["meal"]
    r.append(f"{m['mins']} minute prep")
    if any(x.get("kid") for x in state["members"]) and "kid" in m["tags"]:
        r.append("Kid-friendly")
    if c["unsure"]:
        r.append("Not fully sure about " + ", ".join(f"{e['name']} ({round(e['conf_now'] * 100)}%)" for e in c["unsure"]) + " - worth a quick look")
    return r

def checked_against(c, members):
    res = []
    for p in members:
        parts = []
        if p.get("allergies"):
            parts.append("no " + ", ".join(p["allergies"]) + " ingredients found")
        if p.get("diets"):
            parts.append("fits " + ", ".join(p["diets"]))
        note = "; ".join(parts) if parts else "no restrictions listed"
        res.append({"name": p.get("name") or "Someone", "ok": True, "note": note,
                    "restrictions": list(p.get("allergies", [])) + list(p.get("diets", []))})
    return res

def need_to_buy(c, members):
    out = []
    for k in c["missing"]:
        f = kb.info(k)
        out.append({"key": k, "name": pretty(k), "price": f["price"] if f else 3.0})
    return out

def meal_card(c, state, today):
    m = c["meal"]
    return {"id": m["id"], "name": m["name"], "mins": m["mins"], "steps": m["steps"], "kid": "kid" in m["tags"],
            "score": c.get("score"), "reasons": reasons_for(c, state, today),
            "checked": checked_against(c, state["members"]),
            "need_to_buy": need_to_buy(c, state["members"]),
            "uses": [{"key": e["key"], "name": pretty(e["name"]), "conf": round(e["conf_now"] * 100), "tier": e["tier"],
                      "location": e["location"]} for e in c["used"]],
            "unsure": [e["name"] for e in c["unsure"]], "thaw": [e["name"] for e in c["thaw"]],
            "kitchen_match": round(100 * sum(e["conf_now"] for e in c["used"]) / max(1, len(c["used"]))),
            "breakdown": {"waste": round(sum(URG[e["tier"]] * e["conf_now"] for e in c["used"]), 2),
                          "coverage": f"{c['covered']}/{c['total']}", "mins": m["mins"]}}

def use_soon_list(state, today, n=5):
    pool = _pool(state, today)
    items = [e for e in pool.values() if e["tier"] != "low" or e["key"] in state.get("use_up", {})]
    items.sort(key=lambda e: (-(URG[e["tier"]] + (0.8 if e["key"] in state.get("use_up", {}) else 0)), -e["conf_now"], e["days_left"]))
    return [{"name": pretty(e["name"]), "key": e["key"], "tier": e["tier"], "location": e["location"],
             "conf": round(e["conf_now"] * 100), "days_left": e["days_left"], "risk": round(e["spoilage_risk"] * 100),
             "text": describe_item(e)} for e in items[:n]]

# ---------------------------------------------------------------- tonight

def tonight(state, today, skip=()):
    today = model.d(today)
    today_s = model.iso(today)
    rejected = set(state.get("rejected", {}).get(today_s, [])) | set(skip)
    lock = state.get("week_locks", {}).get(today_s)
    ranked = rank(state, today, exclude=rejected)
    if lock and lock not in rejected and lock in BY_ID:
        c = evaluate(BY_ID[lock], _pool(state, today), state["members"], state.get("use_up", {}))
        if c:
            c["score"] = score(c, state["members"], today, state["history"], state.get("use_up", {}), is_cold(today))
            ranked = [c] + [x for x in ranked if x["meal"]["id"] != lock]
    if not ranked:  # relax
        ranked = rank(state, today, exclude=rejected, min_cov=0.34, max_missing=4)
    res = {"date": today_s, "weekday": today.strftime("%A"), "meal": None, "verify_note": VERIFY_NOTE,
           "use_soon": use_soon_list(state, today), "alternates_left": max(0, len(ranked) - 1), "nudge": None,
           "stale_days": None}
    if state.get("last_photo"):
        age = (today - model.d(state["last_photo"])).days
        if age >= 7:
            res["stale_days"] = age
    if not ranked:
        res["empty"] = ("I don't have enough of a picture of your kitchen to suggest dinner yet. "
                        "Tell the Assistant a few things you have (e.g. 'we have eggs, rice and spinach') or take a photo.")
        return res
    top = ranked[0]
    res["meal"] = meal_card(top, state, today)
    res["nudge"] = freezer_nudge(state, today, top)
    res["_c"] = top
    return res

def freezer_nudge(state, today, tonight_c=None):
    """One gentle nudge: what to move from the freezer to the fridge tonight."""
    today = model.d(today)
    try:
        tom = today + timedelta(days=1)
        locked = state.get("week_locks", {}).get(model.iso(tom))
        cands = []
        if locked and locked in BY_ID:
            c = evaluate(BY_ID[locked], _pool_at(state, tom), state["members"], state.get("use_up", {}), allow_thaw=True)
            cands = [c] if c else []
        else:
            ex = {tonight_c["meal"]["id"]} if tonight_c else set()
            cands = rank(state, tom, allow_thaw=True, exclude=ex, pool=_pool_at(state, tom))[:1]
        for c in cands:
            for e in c["thaw"] or [u for u in c["used"] if u["location"] == "freezer" and "slow" in (kb.info(u["key"]) or {"flags": set()})["flags"]]:
                return {"item": e["name"], "text": f"Move the {e['name']} from the freezer to the fridge tonight - it'll be thawed for tomorrow's {c['meal']['name']}.",
                        "meal": c["meal"]["name"]}
    except Exception:
        pass
    old = [e for e in _pool(state, today).values() if e["location"] == "freezer" and e["tier"] == "use_soon"
           and "slow" in (kb.info(e["key"]) or {"flags": set()})["flags"]]
    if old:
        e = old[0]
        return {"item": e["name"], "text": f"The {e['name']} has been in the freezer a long while. Move it to the fridge tonight and plan to use it in the next couple of days.", "meal": None}
    return None

def _pool_at(state, day):
    return _pool(state, day)

# -------------------------------------------------------------------- week

def week_plan(state, today, budget=None, days=7):
    today = model.d(today)
    st = {**state, "items": [dict(i) for i in state["items"]]}
    planned, extra = [], []
    bought = []
    day_budget = (budget / days) if budget else None
    plan = []
    for i in range(days):
        day = today + timedelta(days=i)
        ds = model.iso(day)
        pool = _pool(st, day)
        for b in bought:  # things we'd have bought for earlier days
            if b not in pool:
                pool[b] = {"key": b, "name": b, "conf_now": 0.9, "tier": "low", "location": "fridge", "days_left": 5, "level": 1, "spoilage_risk": 0}
        rej = set(state.get("rejected", {}).get(ds, [])) if i == 0 else set()
        recent = [{"meal_id": p, "action": "cooked", "date": model.iso(today + timedelta(days=j))} for j, p in enumerate(planned)]
        lock = state.get("week_locks", {}).get(ds)
        c = None
        if lock and lock in BY_ID and lock not in rej:
            c = evaluate(BY_ID[lock], pool, state["members"], state.get("use_up", {}), allow_thaw=i >= 1)
            if c:
                c["score"] = 99
        if not c:
            r = rank(st, day, allow_thaw=i >= 1, exclude=rej | set(planned[-4:]), pool=pool, budget_day=day_budget,
                     min_cov=0.5 if i else 0.6, max_missing=3 if i else 2, extra_hist=recent)
            if not r:
                r = rank(st, day, allow_thaw=True, exclude=rej | set(planned[-2:]), pool=pool, min_cov=0.0, max_missing=6, extra_hist=recent)
            c = r[0] if r else None
        if not c:
            continue
        planned.append(c["meal"]["id"])
        cost = sum((kb.info(k) or {"price": 3})["price"] for k in c["missing"])
        plan.append({"date": ds, "weekday": day.strftime("%A"), "short": day.strftime("%a"), "meal_id": c["meal"]["id"], "name": c["meal"]["name"],
                     "mins": c["meal"]["mins"], "missing": [pretty(k) for k in c["missing"]], "missing_keys": list(c["missing"]),
                     "thaw": [e["name"] for e in c["thaw"]], "locked": bool(lock and lock == c["meal"]["id"]),
                     "uses_soon": [pretty(e["name"]) for e in c["used"] if e["tier"] == "use_soon"][:2],
                     "est_cost": round(cost, 2)})
        bought.extend(c["missing"])
        # simulate consumption
        for e in c["used"]:
            for it in st["items"]:
                if it["key"] == e["key"] and it["location"] == e["location"]:
                    it["level"] = max(0.0, it["level"] - (0.95 if (kb.info(it["key"]) or {"cat": ""})["cat"] not in ("grain", "pantry") else 0.25))
                    break
    total = round(sum(p["est_cost"] for p in plan), 2)
    return {"plan": plan, "est_shopping_cost": total, "budget": budget,
            "within_budget": (total <= budget) if budget else None}

def alternatives_for_day(state, today, date_s, n=6):
    day = model.d(date_s)
    i = (day - model.d(today)).days
    r = rank(state, day, allow_thaw=i >= 1, min_cov=0.5, max_missing=3)
    return [{"meal_id": c["meal"]["id"], "name": c["meal"]["name"], "mins": c["meal"]["mins"],
             "missing": [pretty(k) for k in c["missing"]]} for c in r[:n]]

# ---------------------------------------------------------------- shopping

WATCH = {"milk", "eggs", "bread", "bananas", "yogurt"}

def shopping(state, today):
    today = model.d(today)
    dismissed = {k for k, v in state.get("dismissed", {}).items() if (today - model.d(v)).days < 7}
    out = {"need_soon": [], "running_low": [], "recommended": []}
    seen = set()

    def add(cat, key, name, why, price=None, source="auto", sid=None):
        k = kb.canon(key)[0]
        if k in seen or k in dismissed:
            return
        seen.add(k)
        f = kb.info(k)
        out[cat].append({"key": k, "name": pretty(name), "why": why, "price": price if price is not None else (f["price"] if f else None),
                         "source": source, "id": sid})

    for s in state.get("shopping", []):
        add("need_soon", s["key"], s["name"], "You asked for this" if s.get("source") != "tonight" else "Needed for tonight's dinner",
            source=s.get("source", "user"), sid=s.get("id"))
    wp = week_plan(state, today)["plan"]
    for p in wp[:3]:
        for k in p["missing_keys"]:
            add("need_soon", k, k, f"Needed for {p['weekday']}'s {p['name']}")
    pool = _pool(state, today)
    for key in WATCH:
        its = [model.enrich_item(i, today) for i in state["items"] if i["key"] == key]
        if its:
            best = max(its, key=lambda e: e["conf_now"])
            if best["level"] <= 0.04:
                add("running_low", key, key, "You said it's gone")
            elif best["consumption_probability"] >= 0.55 or best["level"] <= 0.3:
                add("running_low", key, key, f"Probably running low (about {round(max(best['consumption_probability'], 1 - best['level']) * 100)}% chance it's mostly gone)")
        elif state["items"]:
            add("recommended", key, key, "Household staple - I haven't seen any") if key in ("milk", "eggs", "bread") else None
    for it in state["items"]:
        e = model.enrich_item(it, today)
        if e["level"] <= 0.3 and e["conf_now"] >= 0.4 and e["key"] not in WATCH and e["location"] != "freezer" and (kb.info(e["key"]) or {"cat": ""})["cat"] in ("dairy", "grain", "protein", "pantry"):
            add("running_low", e["key"], e["name"], f"Looks low ({conf_word(e['conf_now'])})")
    for p in wp[3:]:
        for k in p["missing_keys"]:
            add("recommended", k, k, f"Would make {p['weekday']}'s {p['name']} possible")
    if state["items"] and not any(k in pool for k in ("spinach", "salad greens", "broccoli", "green beans", "zucchini", "bell pepper", "carrots")):
        add("recommended", "salad greens", "fresh greens or veg", "Nothing green seems to be around")
    for c in out:
        out[c] = out[c][:10]
    return out
