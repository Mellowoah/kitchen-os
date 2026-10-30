"""Kitchen Memory Engine: a probabilistic picture of the kitchen, not an inventory.

Stored per item: name, observed date, purchase date, estimated quantity (level + text),
confidence. Derived on read: spoilage risk, consumption probability, current confidence, use-soon tier.
"""
import math
import uuid
from datetime import date, timedelta
from . import kb

ALLERGENS = ["peanuts", "tree nuts", "dairy", "gluten", "soy", "egg", "shellfish", "fish", "sesame"]
DIETS = ["vegetarian", "vegan", "keto", "low carb", "low sodium", "diabetic"]
FRESH_AGE = {"fresh": 0.1, "ok": 0.35, "aging": 0.7, "spoiling": 0.95, "unknown": 0.3}
AMOUNT_LEVEL = {"full": 1.0, "plenty": 0.85, "some": 0.55, "half": 0.5, "low": 0.25, "almost empty": 0.1, "almost_empty": 0.1}

def d(s):
    return date.fromisoformat(s) if isinstance(s, str) else s

def iso(x):
    return x.isoformat()

def new_state():
    return {"v": 1, "setup_done": False, "members": [], "retailer": None, "items": [], "use_up": {},
            "shopping": [], "history": [], "week_locks": {}, "rejected": {}, "dismissed": {}, "last_photo": None}

def uid():
    return uuid.uuid4().hex[:8]

def clean_state(s):
    """Accepts whatever the client has; fills defaults, drops derived fields."""
    base = new_state()
    base.update({k: v for k, v in (s or {}).items() if k in base})
    for it in base["items"]:
        for k in ("spoilage_risk", "consumption_probability", "conf_now", "tier", "days_left", "age_days", "display"):
            it.pop(k, None)
    return base

# ---------------------------------------------------------------- items

def make_item(name, location=None, today=None, conf=0.9, level=0.8, qty_text="", freshness="unknown",
              purchased=None, source="said", frozen=None, key=None):
    today = d(today) if today else date.today()
    k, known = (key, True) if key else kb.canon(name)
    f = kb.info(k)
    loc = location or (f["loc"] if f else "pantry")
    life = _life(k, loc)
    if purchased:
        pd_, known_p = d(purchased), True
    else:
        age = FRESH_AGE.get(freshness, 0.3) * life if (life <= 60 or freshness != "unknown") else 0
        age = min(age, 14) if loc == "freezer" else age
        if loc == "freezer":
            age = min(life * 0.15, 21)
        pd_, known_p = today - timedelta(days=round(age)), False
    return {"id": uid(), "name": (k if known else name.strip().lower()), "key": k, "known": known, "location": loc,
            "observed": iso(today), "purchased": iso(pd_), "purchase_known": known_p,
            "level": max(0.0, min(1.0, level)), "qty_text": qty_text, "conf": max(0.05, min(0.99, conf)),
            "freshness": freshness, "source": source, "frozen": iso(pd_) if loc == "freezer" else None}

def _life(key, loc):
    f = kb.info(key)
    if not f:
        return kb.GENERIC_LIFE.get(loc, 30)
    if loc == "freezer":
        return f["freezer"] or 120
    if f["loc"] == "freezer":  # defaults to freezer items found elsewhere -> short
        return 14
    return f["life"]

def rate(key):
    f = kb.info(key)
    return kb.RATE_KEY.get(key) or kb.RATE.get(f["cat"] if f else "other", 0.01)

def enrich_item(it, today):
    today = d(today)
    key, loc = it["key"], it["location"]
    life = _life(key, loc)
    ref = d(it["frozen"] or it["purchased"]) if loc == "freezer" and it.get("frozen") else d(it["purchased"])
    age = max(0, (today - ref).days)
    since_obs = max(0, (today - d(it["observed"])).days)
    ratio = age / life if life else 0
    risk = max(0.0, min(1.0, ratio ** 1.4)) if loc != "freezer" else max(0.0, min(1.0, ratio ** 3))
    left = life - age
    cons_p = 1 - math.exp(-rate(key) * since_obs)
    conf_now = it["conf"] * (1 - 0.85 * cons_p)
    if loc == "freezer":
        tier = "use_soon" if left <= 14 else ("use_week" if left <= 45 else "low")
    else:
        tier = "use_soon" if (left <= 2 and life <= 60) or risk >= 0.6 else ("use_week" if (left <= 7 and life <= 90) or risk >= 0.35 else "low")
    out = dict(it)
    out.update(age_days=age, days_left=left, spoilage_risk=round(risk, 2), consumption_probability=round(cons_p, 2),
               conf_now=round(conf_now, 2), tier=tier)
    return out

def enrich(state, today):
    st = dict(state)
    st["items"] = [enrich_item(i, today) for i in state["items"]]
    return st

def present(items, min_conf=0.25):
    """Items we still think are around."""
    return [i for i in items if i["conf_now"] >= min_conf and i["level"] > 0.04]

# --------------------------------------------------------------- updates

def merge_observation(state, detected, location, today, decay=True):
    """Merge items seen in a photo of `location`. Items previously believed there and not seen lose confidence."""
    today = d(today)
    seen = set()
    for det in detected:
        name = det.get("name", "")
        if not name:
            continue
        loc = det.get("location") or location
        it = make_item(name, loc, today, conf=float(det.get("confidence", 0.7)),
                       level=AMOUNT_LEVEL.get(str(det.get("amount", "some")).lower(), 0.55),
                       qty_text=det.get("quantity", "") or "", freshness=det.get("freshness", "unknown"), source="photo")
        existing = next((e for e in state["items"] if e["key"] == it["key"] and e["location"] == it["location"]), None)
        seen.add((it["key"], it["location"]))
        if existing:
            existing.update(observed=it["observed"], conf=max(it["conf"], 0.5), level=it["level"], qty_text=it["qty_text"] or existing["qty_text"],
                            freshness=it["freshness"])
        else:
            state["items"].append(it)
    for e in state["items"]:
        if decay and e["location"] == location and (e["key"], e["location"]) not in seen and e["observed"] != iso(today):
            e["conf"] = round(e["conf"] * 0.5, 2)
    state["last_photo"] = iso(today)
    return state

def find_items(state, name):
    k, _ = kb.canon(name)
    return [i for i in state["items"] if i["key"] == k or kb.norm(i["name"]) == kb.norm(name)]

def add_item(state, name, today, location=None, source="said"):
    k, known = kb.canon(name)
    f = kb.info(k)
    loc = location or (f["loc"] if f else "fridge")
    ex = next((i for i in state["items"] if i["key"] == k and i["location"] == loc), None)
    if ex:
        ex.update(observed=iso(d(today)), purchased=iso(d(today)), purchase_known=True, level=1.0, conf=0.95, source=source,
                  freshness="fresh")
        return ex
    it = make_item(name, loc, today, conf=0.95, level=1.0, freshness="fresh", purchased=today, source=source)
    state["items"].append(it)
    return it

def use_all(state, name):
    hits = find_items(state, name)
    for h in hits:
        h["level"] = 0.0
        h["conf"] = 0.95
    return hits

def use_some(state, name, frac=0.5):
    hits = find_items(state, name)
    for h in hits:
        h["level"] = round(h["level"] * (1 - frac), 2)
        if h["level"] < 0.12:
            h["level"] = 0.0
    return hits

def prune(state, today):
    """Forget items that are very probably gone, so the model never grows into a ledger."""
    keep = []
    for it in state["items"]:
        e = enrich_item(it, today)
        if it["level"] <= 0.04 and (d(today) - d(it["observed"])).days > 14:
            continue
        if e["conf_now"] < 0.06:
            continue
        keep.append(it)
    state["items"] = keep
    return state

# ------------------------------------------------------------ restrictions

def member_conflicts(member, key):
    """Return reasons ingredient `key` conflicts with this person. Unknown foods can't be checked."""
    f = kb.info(key)
    if not f:
        return []
    reasons = []
    for a in member.get("allergies", []):
        if a in f["allergens"]:
            reasons.append(f"{key} contains {a}")
    diets = set(member.get("diets", []))
    fl = f["flags"]
    if "vegan" in diets and (fl & {"animal", "meat", "fish", "shellfish"} or f["allergens"] & {"dairy", "egg", "fish", "shellfish"}):
        reasons.append(f"{key} isn't vegan")
    elif "vegetarian" in diets and (fl & {"meat", "fish", "shellfish"} or f["allergens"] & {"fish", "shellfish"}):
        reasons.append(f"{key} isn't vegetarian")
    if "keto" in diets and (fl & {"carb", "sugar"}):
        reasons.append(f"{key} is high-carb")
    elif "low carb" in diets and "carb" in fl:
        reasons.append(f"{key} is high-carb")
    if "low sodium" in diets and "sodium" in fl:
        reasons.append(f"{key} is high-sodium")
    if "diabetic" in diets and (fl & {"sugar", "refined"}):
        reasons.append(f"{key} is high in sugar/refined carbs")
    return reasons

def ok_for_all(members, key):
    return not any(member_conflicts(m, key) for m in members)
