import base64, os, json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import ai, assistant, engine, kb, model
from .meals import BY_ID

app = FastAPI(title="Kitchen OS", docs_url=None, redoc_url=None)
STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")

def today_of(body):
    t = (body or {}).get("today")
    try:
        if t:
            return model.iso(model.d(t))
    except Exception:
        pass
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()

def st_of(body):
    return model.clean_state((body or {}).get("state"))

def public(state):
    return state

def client_ip(req: Request):
    return (req.headers.get("x-forwarded-for") or (req.client.host if req.client else "x")).split(",")[0].strip()

@app.get("/api/health")
def health():
    return {"ok": True, "ai": ai.available(), "vision_models": ai.VISION_MODELS if ai.available() else []}

# ------------------------------------------------------------------ setup

@app.post("/api/photos")
async def photos(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    pics = (body.get("photos") or [])[:3]
    results = []
    if not ai.available():
        return {"state": state, "results": [{"kind": p.get("kind"), "ok": False, "error": "AI vision isn't configured on this server."} for p in pics], "ai": False}
    if not ai.allow(client_ip(req), limit=30):
        raise HTTPException(429, "Too many photo requests this hour - try again later.")

    def work(p):
        kind = p.get("kind", "fridge")
        try:
            data = p.get("image", "")
            mime = "image/jpeg"
            if data.startswith("data:"):
                head, data = data.split(",", 1)
                mime = head[5:].split(";")[0] or mime
            raw = base64.b64decode(data)
            if len(raw) > 6_000_000:
                return {"kind": kind, "ok": False, "error": "Photo too large."}
            items, note, mdl = ai.vision_items(raw, mime, kind)
            return {"kind": kind, "ok": True, "items": items, "note": note, "model": mdl}
        except Exception as e:  # noqa
            return {"kind": kind, "ok": False, "error": "Couldn't read this photo (" + str(e)[:80] + ")"}

    with ThreadPoolExecutor(3) as ex:
        results = list(ex.map(work, pics))
    for r in results:
        if r["ok"]:
            dets = [{"name": i.get("name", ""), "confidence": i.get("confidence", 0.6), "quantity": i.get("quantity", ""),
                     "amount": i.get("amount", "some"), "freshness": i.get("freshness", "unknown")} for i in r["items"]
                    if i.get("name") and "unknown" not in i["name"].lower()]
            unknown = [i for i in r["items"] if "unknown" in (i.get("name") or "").lower()]
            is_room = r["kind"] in ("fridge", "freezer", "pantry")
            model.merge_observation(state, dets, r["kind"] if is_room else "fridge", today, decay=is_room)
            r["items"] = [{"name": i["name"], "confidence": round(i["confidence"] * 100)} for i in r["items"]]
            r["unknown_count"] = len(unknown)
    return {"state": state, "results": results, "ai": True}

DEMO = [  # a plausible sample kitchen for trying the app without photos (clearly labeled as sample in the UI)
    ("chicken thighs", "fridge", .88, "aging"), ("milk", "fridge", .8, "ok"), ("eggs", "fridge", .95, "ok"), ("spinach", "fridge", .66, "aging"),
    ("yogurt", "fridge", .85, "ok"), ("cheddar", "fridge", .8, "ok"), ("broccoli", "fridge", .75, "ok"), ("carrots", "fridge", .8, "ok"),
    ("bell pepper", "fridge", .7, "ok"), ("butter", "fridge", .9, "ok"), ("salsa", "fridge", .8, "ok"), ("tortillas", "fridge", .7, "ok"),
    ("ground beef", "freezer", .8, "ok"), ("shrimp", "freezer", .75, "ok"), ("frozen pizza", "freezer", .9, "ok"), ("mixed vegetables", "freezer", .85, "ok"),
    ("chicken breast", "freezer", .82, "ok"),
    ("pasta", "pantry", .92, "ok"), ("rice", "pantry", .9, "ok"), ("pasta sauce", "pantry", .85, "ok"), ("canned tomatoes", "pantry", .85, "ok"),
    ("black beans", "pantry", .8, "ok"), ("onion", "pantry", .85, "ok"), ("potatoes", "pantry", .8, "ok"), ("soy sauce", "pantry", .85, "ok"),
    ("bread", "pantry", .7, "aging"), ("peanut butter", "pantry", .9, "ok")]

@app.post("/api/demo")
async def demo(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    for name, loc, conf, fresh in DEMO:
        it = model.make_item(name, loc, today, conf=conf, level=0.7, freshness=fresh, source="sample")
        state["items"].append(it)
    state["last_photo"] = today
    return {"state": state}

# ---------------------------------------------------------------- tonight

def clean_tonight(t):
    t.pop("_c", None)
    return t

@app.post("/api/tonight")
async def tonight(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    return {"tonight": clean_tonight(engine.tonight(state, today))}

@app.post("/api/tonight/action")
async def tonight_action(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    action, meal_id = body.get("action"), body.get("meal_id")
    if meal_id not in BY_ID:
        raise HTTPException(400, "unknown meal")
    if action == "cook":
        c = engine.evaluate(BY_ID[meal_id], engine._pool(state, today), state["members"], state.get("use_up", {}))
        used = []
        if c:
            for e in c["used"] + c["extras"]:
                for it in state["items"]:
                    if it["key"] == e["key"] and it["location"] == e["location"]:
                        cat = (kb.info(it["key"]) or {"cat": "other"})["cat"]
                        it["level"] = round(max(0.0, it["level"] - (0.7 if cat not in ("grain", "pantry") else 0.3)), 2)
                        if it["level"] < 0.12:
                            it["level"] = 0.0
                        used.append(it["name"])
                        state["use_up"].pop(it["key"], None)
        state["history"].append({"date": today, "meal_id": meal_id, "action": "cooked"})
        state["history"] = state["history"][-60:]
        state["week_locks"].pop(today, None)
        model.prune(state, today)
        return {"state": state, "message": f"Enjoy! I'll assume you used up the {', '.join(sorted(set(used))[:5])} - say so if that's off.", "used": used}
    if action == "alternate":
        state["rejected"].setdefault(today, []).append(meal_id)
        state["history"].append({"date": today, "meal_id": meal_id, "action": "rejected"})
        state["history"] = state["history"][-60:]
        state["rejected"] = {k: v for k, v in state["rejected"].items() if k == today}
        return {"state": state, "tonight": clean_tonight(engine.tonight(state, today))}
    if action == "add_missing":
        c = engine.evaluate(BY_ID[meal_id], engine._pool(state, today), state["members"], state.get("use_up", {}))
        added = []
        for k in (c["missing"] if c else []):
            if not any(s["key"] == k for s in state["shopping"]):
                state["shopping"].append({"id": model.uid(), "name": k, "key": k, "added": today, "source": "tonight"})
                added.append(engine.pretty(k))
        state["dismissed"].pop("x", None)
        return {"state": state, "added": added}
    raise HTTPException(400, "unknown action")

@app.post("/api/explain")
async def explain(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    t = engine.tonight(state, today)
    if not t.get("meal"):
        return {"text": t.get("empty", ""), "source": "rules"}
    if body.get("meal_id") and body["meal_id"] != t["meal"]["id"]:
        c = engine.evaluate(BY_ID[body["meal_id"]], engine._pool(state, today), state["members"], state.get("use_up", {}))
        card = engine.meal_card({**c, "score": 0}, state, today) if c else t["meal"]
    else:
        card = t["meal"]
    others = []
    for c in engine.rank(state, today, exclude={card["id"]})[:3]:
        others.append(c["meal"]["name"])
    plain = (f"{card['name']} ranked first because it makes use of food that's probably nearing its time "
             f"({'; '.join(r for r in card['reasons'][:2])}). It needs {card['breakdown']['coverage']} of its main ingredients that I think you have, "
             f"takes {card['mins']} minutes, and nothing in it conflicts with what you told me about the household. "
             f"Runners-up: {', '.join(others) or 'none'}. My picture of your kitchen is a guess - and always verify labels.")
    out = {"text": plain, "source": "rules", "breakdown": card["breakdown"], "runners_up": others}
    if ai.available() and ai.allow(client_ip(req), limit=120):
        try:
            prompt = ("Explain in 3 short sentences, warm and plain, why this dinner was picked for a household. Mention what's likely to spoil first, "
                      "that the kitchen picture is an estimate (give no certainty), and end by reminding them to verify labels for allergies. "
                      "Do NOT claim the meal is allergy-safe. Facts: " + json.dumps({"meal": card["name"], "reasons": card["reasons"], "checked_against": card["checked"],
                      "need_to_buy": [b["name"] for b in card["need_to_buy"]], "runners_up": others, "minutes": card["mins"]}))
            txt, mdl = ai.generate([{"text": prompt}], None, timeout=15)
            out.update(text=txt, source="ai:" + mdl)
        except Exception:
            pass
    return out

# --------------------------------------------------------------- week / shop

@app.post("/api/week")
async def week(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    return engine.week_plan(state, today, budget=body.get("budget"))

@app.post("/api/week/alternatives")
async def week_alt(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    return {"alternatives": engine.alternatives_for_day(state, today, body["date"])}

@app.post("/api/week/lock")
async def week_lock(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    if body.get("meal_id") not in BY_ID:
        raise HTTPException(400, "unknown meal")
    state["week_locks"][body["date"]] = body["meal_id"]
    state["week_locks"] = {k: v for k, v in state["week_locks"].items() if k >= today}
    return {"state": state, "week": engine.week_plan(state, today)}

@app.post("/api/shopping")
async def shopping(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    return {"shopping": engine.shopping(state, today), "retailer": state.get("retailer")}

@app.post("/api/shopping/bought")
async def bought(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    name = body.get("name", "")
    model.add_item(state, name, today, source="shopping")
    k = kb.canon(name)[0]
    state["shopping"] = [s for s in state["shopping"] if s["key"] != k]
    return {"state": state, "shopping": engine.shopping(state, today)}

@app.post("/api/shopping/dismiss")
async def dismiss(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    k = kb.canon(body.get("name", ""))[0]
    state["shopping"] = [s for s in state["shopping"] if s["key"] != k]
    state["dismissed"][k] = today
    return {"state": state, "shopping": engine.shopping(state, today)}

@app.post("/api/add")
async def add(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    for n in (body.get("names") or [])[:30]:
        model.add_item(state, str(n)[:40], today, source=body.get("source", "said"))
    return {"state": state}

# ------------------------------------------------------------- assistant etc

@app.post("/api/assistant")
async def assistant_ep(req: Request):
    body = await req.json()
    state, today = st_of(body), today_of(body)
    msg = str(body.get("message", ""))[:500]
    if not ai.allow(client_ip(req), limit=200, window=3600):
        raise HTTPException(429, "Slow down a little - try again in a bit.")
    return assistant.handle(state, msg, today, body.get("history"))

@app.post("/api/kitchen")
async def kitchen(req: Request):
    """Read-only 'what I think is in your kitchen' view (kept out of the main UI on purpose)."""
    body = await req.json()
    state, today = st_of(body), today_of(body)
    es = model.enrich(state, today)["items"]
    es = [e for e in es if e["level"] > 0.04 and e["conf_now"] >= 0.15]
    order = {"use_soon": 0, "use_week": 1, "low": 2}
    es.sort(key=lambda e: (order[e["tier"]], -e["conf_now"]))
    return {"items": [{k: e[k] for k in ("name", "location", "observed", "purchased", "qty_text", "level", "conf_now", "spoilage_risk",
                                          "consumption_probability", "tier", "days_left")} for e in es]}

@app.post("/api/receipt")
async def receipt(req: Request):
    """STUB: real receipt OCR isn't built. Returns a canned receipt so the confirm flow can be tried."""
    return {"stub": True, "note": "Demo receipt - OCR isn't built yet.", "items": [
        {"name": "Whole milk", "confidence": 94}, {"name": "Bananas", "confidence": 91}, {"name": "Chicken breast", "confidence": 88},
        {"name": "Baby spinach", "confidence": 72}, {"name": "Greek yogurt", "confidence": 58}, {"name": "Unreadable line", "confidence": 22}]}

@app.post("/api/retailer")
async def retailer(req: Request):
    """MOCK: no real retailer connection. Stores the choice only."""
    body = await req.json()
    state = st_of(body)
    state["retailer"] = body.get("retailer")
    return {"state": state, "mock": True}

@app.post("/api/cart")
async def cart(req: Request):
    """MOCK: pretend to send the list to the connected retailer."""
    body = await req.json()
    state, today = st_of(body), today_of(body)
    sh = engine.shopping(state, today)
    names = [x["name"] for x in sh["need_soon"]]
    return {"mock": True, "retailer": state.get("retailer"), "items": names,
            "message": f"Demo only: nothing was ordered. With a real connection I'd build a {state.get('retailer') or 'store'} cart with {len(names)} items for you to review."}

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})

@app.get("/guide")
@app.get("/about")
def guide():
    return FileResponse(os.path.join(STATIC, "guide.html"), media_type="text/html", headers={"Cache-Control": "no-cache"})

@app.get("/sw.js")
def sw():
    return FileResponse(os.path.join(STATIC, "sw.js"), media_type="application/javascript", headers={"Cache-Control": "no-cache"})

@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(STATIC, "manifest.webmanifest"), media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})

app.mount("/", StaticFiles(directory=STATIC), name="static")
