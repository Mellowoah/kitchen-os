"""The Assistant: understands natural statements, updates the kitchen model. Rules first (instant, works offline), LLM for the rest."""
import re, json
from . import kb, model, engine, ai
from .meals import MEALS

def _split(s):
    s = re.sub(r"[.!?]+$", "", s.strip())
    s = re.sub(r"\bhalf\s*(?:&|and)\s*half\b", "half_and_half", s, flags=re.I)  # one item, not two
    parts = re.split(r",|\band\b|&|\bplus\b", s)
    out = []
    for p in parts:
        p = re.sub(r"^(?:all|any|some|the|our|my|more|a|an|of|rest of|the rest of|a bit of|a little)\s+", "", p.strip())
        p = re.sub(r"^(?:all|any|some|the|our|my|of|rest of|more)\s+", "", p.strip())
        p = re.sub(r"\s+(?:today|tonight|yesterday|now|already|too|as well|again|please)$", "", p.strip())
        p = p.replace("half_and_half", "half and half")
        if p:
            out.append(p)
    return out

P_USED_ALL = re.compile(r"^(?:we|i)(?:'ve|’ve| have|'re|’re| are)?\s*(?:just\s+)?(?:used up|used|finished|ate|eaten|run out of|ran out of|out of|got rid of|threw out|tossed)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|our\s+)?(.+)$")
P_USED_ALL2 = re.compile(r"^(?:no more|out of|ran out of|we have no|we have no more|there(?:'s| is) no)\s+(.+)$")
P_USED_SOME = re.compile(r"^(?:we|i)(?:'ve| have)?\s*(?:used|ate|eaten|had)\s+(?:some|half|a bit|a little|part)\s+(?:of\s+)?(?:the\s+|our\s+)?(.+)$")
P_USE_UP = re.compile(r"^(?:please\s+)?(?:use up|use|need to use(?: up)?|have to use(?: up)?|let'?s use(?: up)?|help me use(?: up)?|should use(?: up)?|want to use(?: up)?)\s+(?:the\s+|our\s+|my\s+|some\s+)?(.+?)(?:\s+(?:soon|first|up|tonight|this week))?$")
P_SHOP = [re.compile(p) for p in (
    r"^add\s+(.+?)\s+to\s+(?:the\s+|my\s+|our\s+)?(?:shopping|grocery|buy)(?:\s+list)?$",
    r"^put\s+(.+?)\s+on\s+(?:the\s+|my\s+|our\s+)?(?:shopping|grocery)(?:\s+list)?$",
    r"^(?:we|i)\s+(?:need|should buy|have to buy|need to buy|want)\s+(?:to buy\s+)?(.+)$",
    r"^(?:need to buy|remind me to buy|remind me to get|buy|get|pick up)\s+(.+)$")]
P_HAVE = [re.compile(p) for p in (
    r"^(?:we|i)(?:'ve| have)?\s*(?:just\s+|also\s+|now\s+)*(?:have|got|bought|picked up|purchased|grabbed|got back with)\s+(.+)$",
    r"^(?:we|i) (?:just )?(?:bought|got)\s+(.+)$",
    r"^(?:there(?:'s| is| are))\s+(.+?)\s+(?:in the (?:fridge|freezer|pantry))$",
    r"^(?:add|adding|also add)\s+(.+)$",
    r"^(?:bought|got)\s+(.+)$")]

def _resolve_names(parts):
    out = []
    for p in parts:
        k, known = kb.canon(p)
        out.append((p, k, known))
    return out

def _cards(cands, state, n=4):
    return [{"name": c["meal"]["name"], "mins": c["meal"]["mins"], "missing": [engine.pretty(k) for k in c["missing"]],
             "id": c["meal"]["id"]} for c in cands[:n]]

def handle(state, message, today, history=None):
    msg = (message or "").strip()
    low = re.sub(r"\s+", " ", msg.lower().replace("’", "'")).strip()
    low = re.sub(r"^(?:hey|hi|ok|okay|so|um|please|can you|could you|just)\s+", "", low)
    low = re.sub(r"\s+please$", "", low)
    reply, changes, cards, nav = "", [], [], None
    today_s = model.iso(model.d(today))

    def done(reply, source="rules", **extra):
        model.prune(state, today)
        return {"reply": reply, "changes": changes, "cards": cards, "navigate": nav, "state": state, "source": source, **extra}

    # --- questions first
    if re.search(r"what(?:'s| is| are we| should we| do we)?.*(?:for dinner|eating|eat tonight|cook tonight|make tonight|have for dinner)|^dinner\??$|what'?s for dinner", low):
        t = engine.tonight(state, today)
        if t.get("meal"):
            m = t["meal"]
            buy = (" You'd need: " + ", ".join(b["name"] for b in m["need_to_buy"]) + ".") if m["need_to_buy"] else " I think you have everything."
            nav = "tonight"
            return done(f"I'd go with {m['name']} ({m['mins']} min). {m['reasons'][0]}.{buy}", cards=[])
        return done(t.get("empty", "I'm not sure yet - tell me what's in the kitchen."))
    if re.search(r"expire|go(?:ing)? bad|use soon|use first|spoil|about to|what should (?:i|we) use", low) and not P_USE_UP.match(low):
        us = engine.use_soon_list(state, today, 6)
        if not us:
            return done("Nothing looks urgent based on what I know - but my picture may be out of date. A quick fridge photo helps.")
        return done("Here's what I'd use first (my best guess, not a guarantee):\n" + "\n".join(f"- {u['text']}" for u in us))
    if re.search(r"shopping list|grocery list|what (?:do )?(?:we|i) need to buy|what should (?:i|we) buy", low) and not any(p.match(low) for p in P_SHOP):
        sh = engine.shopping(state, today)
        lines = []
        for lab, k in (("Need soon", "need_soon"), ("Running low", "running_low"), ("Recommended", "recommended")):
            if sh[k]:
                lines.append(f"{lab}: " + ", ".join(x["name"] for x in sh[k][:6]))
        nav = "shopping"
        return done("\n".join(lines) or "Nothing I'd flag right now.")
    m = re.search(r"(?:cook|make|do|eat|dinner|meal)s?\s+(?:with|using|from)\s+(?:the\s+|some\s+|our\s+)?(.+?)\??$", low) or re.search(r"what can (?:i|we) (?:cook|make) with (.+?)\??$", low)
    if m:
        names = _split(m.group(1))
        keys = [kb.canon(n)[0] for n in names]
        pool = engine._pool(state, today)
        cands = engine.rank(state, today, dinner_only=False, types=["dinner", "lunch"], min_cov=0.0, max_missing=4)
        cands = [c for c in cands if any(any(k in g.split("|") for k in keys) for g in c["meal"]["req"] + c["meal"]["opt"])]
        if not cands:
            return done(f"I couldn't find a good fit with {', '.join(names)} given everyone's restrictions.")
        cards = _cards(cands, state, 4)
        return done(f"Ideas with {', '.join(names)}: " + "; ".join(f"{c['name']} ({c['mins']} min" + (f", need {', '.join(c['missing'])}" if c["missing"] else "") + ")" for c in cards))
    m = re.search(r"(?:meal plan|plan (?:the )?(?:meals|week|dinners)|plan meals).*?(?:under|below|for|within|\$)\s*\$?\s*(\d+)", low) or re.search(r"under \$?\s*(\d+)", low)
    if m and re.search(r"plan|meals|week", low):
        budget = float(m.group(1))
        w = engine.week_plan(state, today, budget=budget)
        nav = "week"
        return done(f"Here's a week around ${budget:.0f}. Groceries I'd still need come to roughly ${w['est_shopping_cost']:.0f} "
                    f"({'within' if w['within_budget'] else 'over'} your budget - prices are rough guesses, not real store prices).", budget=budget)
    if re.search(r"plan (?:the |my |our )?(?:week|meals|dinners)|meal plan|this week", low):
        nav = "week"
        return done("I've lined up the week - tap any day to swap a meal.")
    if re.search(r"lunch", low):
        cands = engine.rank(state, today, dinner_only=False, types=["lunch"], min_cov=0.5, max_missing=2)
        cards = _cards(cands, state, 5)
        return done("Lunch ideas from what you probably have: " + ("; ".join(f"{c['name']} ({c['mins']} min)" for c in cards) if cards else "nothing great - tell me what's around."))
    if re.search(r"kid|child|toddler", low) and re.search(r"meal|idea|dinner|food|recipe|friendly", low):
        cands = [c for c in engine.rank(state, today, min_cov=0.5, max_missing=2) if "kid" in c["meal"]["tags"]]
        cards = _cards(cands, state, 5)
        return done("Kid-friendly options: " + ("; ".join(f"{c['name']} ({c['mins']} min)" for c in cards) if cards else "none that fit everyone's restrictions right now."))
    if re.search(r"what (?:do )?(?:we|i) have|what'?s in the (?:fridge|kitchen|freezer|pantry)", low):
        pool = engine._pool(state, today)
        top = sorted(pool.values(), key=lambda e: -e["conf_now"])[:12]
        return done("My rough picture (not a count): " + ", ".join(f"{e['name']} ({round(e['conf_now']*100)}%)" for e in top) if top else "I don't have a picture yet.")

    # --- statements that update the model
    mt = P_USED_SOME.match(low)
    if mt:
        for raw, k, known in _resolve_names(_split(mt.group(1))):
            hits = model.use_some(state, raw)
            changes.append(f"{engine.pretty(k)}: about half used" if hits else f"{engine.pretty(k)}: wasn't on my radar")
        return done("Got it - I'll assume there's about half left. " + "; ".join(changes))
    mt = P_USED_ALL.match(low) or P_USED_ALL2.match(low)
    if mt and not P_HAVE[0].match(low):
        names = _split(mt.group(1))
        for raw, k, known in _resolve_names(names):
            hits = model.use_all(state, raw)
            if not hits:
                changes.append(f"{engine.pretty(k)}: wasn't in my picture, noted as out")
            else:
                changes.append(f"{engine.pretty(k)}: marked as used up")
            if k in engine.WATCH or kb.info(k):
                pass
        return done("Noted - " + "; ".join(changes) + ". I'll factor that in" + (" and flag it on your shopping list." if any(kb.canon(n)[0] in engine.WATCH for n in names) else "."), navigate=None)
    mt = P_USE_UP.match(low)
    if mt and not re.match(r"^use\s+(?:the\s+)?(?:oven|stove|microwave|app)", low):
        names = _split(mt.group(1))
        got = []
        for raw, k, known in _resolve_names(names):
            state["use_up"][k] = today_s
            got.append(k)
            if not model.find_items(state, raw):
                model.add_item(state, raw, today, source="said")
                changes.append(f"{engine.pretty(k)}: wasn't in my picture, added")
            changes.append(f"{engine.pretty(k)}: prioritized")
        t = engine.tonight(state, today)
        extra = ""
        if t.get("meal"):
            extra = f" Tonight I'd make {t['meal']['name']}."
            nav = "tonight"
        return done(f"Got it - I'll plan around using up {', '.join(engine.pretty(k) for k in got).lower()}.{extra}")
    for p in P_SHOP:
        mt = p.match(low)
        if mt:
            names = _split(mt.group(1))
            for raw, k, known in _resolve_names(names):
                if not any(s["key"] == k for s in state["shopping"]):
                    state["shopping"].append({"id": model.uid(), "name": k if known else raw, "key": k, "added": today_s, "source": "assistant"})
                changes.append(f"{engine.pretty(k)}: on your shopping list")
            nav = "shopping"
            return done("Added to your list: " + ", ".join(engine.pretty(kb.canon(n)[0]) for n in names) + ".")
    for p in P_HAVE:
        mt = p.match(low)
        if mt:
            names = _split(mt.group(1))
            if not names or re.search(r"\b(?:question|idea|plan|time)\b", mt.group(1)):
                break
            for raw, k, known in _resolve_names(names):
                model.add_item(state, raw, today, source="said")
                state["shopping"] = [s for s in state["shopping"] if s["key"] != k]
                changes.append(f"{engine.pretty(k)}: added")
            plural = len(names) > 1
            return done(("Added " + ", ".join(engine.pretty(kb.canon(n)[0]).lower() for n in names)
                         + " - I'll assume " + ("they're fresh." if plural else "it's fresh.")), navigate=None)

    # --- anything else -> LLM
    if ai.available():
        try:
            return _llm(state, msg, today, history or [], done)
        except Exception as e:  # noqa
            return done("I couldn't reach my AI helper just now. I can still handle things like 'we used all the yogurt', 'add milk', "
                        "'use up spinach', 'what's for dinner?', or 'make a shopping list'.", source="fallback")
    return done("I can handle things like 'we used all the yogurt', 'add milk', 'use up spinach', 'what's for dinner?', or 'make a shopping list'.", source="fallback")

SYS = """You are Kitchen OS's assistant, a calm household helper that helps decide what's for dinner. You only have a ROUGH, probabilistic picture of the kitchen; never claim certainty and never claim any food is safe for an allergy - remind users to verify labels when allergies come up. Be brief (1-3 sentences), warm, practical.
Return JSON: {"reply": string, "actions": [ {"type": one of "add_item"|"used_all"|"used_some"|"use_up"|"shopping_add"|"navigate", "name": string (food, for item actions), "tab": "tonight"|"week"|"shopping"|"assistant" (for navigate)} ]}.
Only include actions the user clearly asked for or stated (e.g. 'we're out of eggs' -> used_all eggs). If the user just asks a question, answer from the kitchen picture and return no actions."""

def _summary(state, today):
    pool = engine._pool(state, today)
    items = sorted(pool.values(), key=lambda e: (-engine.URG[e["tier"]], -e["conf_now"]))[:40]
    t = engine.tonight(state, today)
    return json.dumps({
        "household": [{"name": m["name"], "allergies": m["allergies"], "diets": m["diets"], "kid": bool(m.get("kid"))} for m in state["members"]],
        "kitchen_guess": [{"item": e["name"], "where": e["location"], "sure": round(e["conf_now"], 2), "use": e["tier"]} for e in items],
        "tonights_pick": (t["meal"]["name"] if t.get("meal") else None),
        "shopping_list": [s["name"] for s in state["shopping"]],
        "meal_library": [m["name"] for m in MEALS][:60]})

def _llm(state, msg, today, history, done):
    hist = "\n".join(f"{h.get('role','user')}: {h.get('text','')}" for h in history[-6:])
    prompt = f"KITCHEN CONTEXT: {_summary(state, today)}\n\nRECENT CHAT:\n{hist}\n\nUSER: {msg}"
    schema = {"type": "OBJECT", "properties": {"reply": {"type": "STRING"}, "actions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "type": {"type": "STRING"}, "name": {"type": "STRING"}, "tab": {"type": "STRING"}}, "required": ["type"]}}}, "required": ["reply"]}
    res, mdl = ai.generate([{"text": prompt}], schema, system=SYS, timeout=25)
    changes, nav = [], None
    today_s = model.iso(model.d(today))
    for a in (res.get("actions") or [])[:6]:
        t, name = a.get("type"), (a.get("name") or "").strip()
        if t == "navigate" and a.get("tab") in ("tonight", "week", "shopping", "assistant"):
            nav = a["tab"]
        elif name and len(name) < 40:
            k, known = kb.canon(name)
            if t == "add_item":
                model.add_item(state, name, today); changes.append(f"{engine.pretty(k)}: added")
            elif t == "used_all":
                model.use_all(state, name); changes.append(f"{engine.pretty(k)}: marked as used up")
            elif t == "used_some":
                model.use_some(state, name); changes.append(f"{engine.pretty(k)}: about half used")
            elif t == "use_up":
                state["use_up"][k] = today_s; changes.append(f"{engine.pretty(k)}: prioritized")
            elif t == "shopping_add" and not any(s["key"] == k for s in state["shopping"]):
                state["shopping"].append({"id": model.uid(), "name": k if known else name.lower(), "key": k, "added": today_s, "source": "assistant"})
                changes.append(f"{engine.pretty(k)}: on your shopping list")
    model.prune(state, today)
    return {"reply": res.get("reply", "Okay."), "changes": changes, "cards": [], "navigate": nav, "state": state, "source": "ai:" + mdl}
