"""Gemini wrapper (server-side only). The key never leaves this process."""
import base64, json, os, time, threading
import requests

KEY = lambda: os.environ.get("LLM_API_KEY", "")
BASE = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
VISION_MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
TEXT_MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite"]

class AIError(Exception):
    pass

def available():
    return bool(KEY())

def _call(model, parts, schema=None, timeout=40, temperature=0.3, system=None):
    cfg = {"temperature": temperature, "thinkingConfig": {"thinkingLevel": "low"}}
    if schema is not None:
        cfg["responseMimeType"] = "application/json"
        if isinstance(schema, dict):
            cfg["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    r = requests.post(BASE.format(m=model), headers={"x-goog-api-key": KEY(), "Content-Type": "application/json"},
                      json=body, timeout=timeout)
    if r.status_code != 200:
        raise AIError(f"{model}: HTTP {r.status_code}")
    j = r.json()
    try:
        txt = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"] if not p.get("thought"))
    except Exception:
        raise AIError(f"{model}: empty response")
    if schema is not None:
        try:
            return json.loads(txt)
        except Exception:
            raise AIError(f"{model}: bad JSON")
    return txt.strip()

def generate(parts, schema=None, models=None, timeout=40, temperature=0.3, system=None):
    if not available():
        raise AIError("no key configured")
    last = None
    for m in models or TEXT_MODELS:
        try:
            return _call(m, parts, schema, timeout, temperature, system), m
        except Exception as e:  # noqa
            last = e
    raise AIError(str(last))

ITEMS_SCHEMA = {"type": "OBJECT", "properties": {"items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "name": {"type": "STRING"}, "confidence": {"type": "NUMBER"}, "quantity": {"type": "STRING"},
    "amount": {"type": "STRING"}, "freshness": {"type": "STRING"}, "shelf": {"type": "STRING"}, "brand": {"type": "STRING"}},
    "required": ["name", "confidence"]}}, "note": {"type": "STRING"}}, "required": ["items"]}

def vision_items(image_bytes, mime, kind):
    prompt = (
        f"You are the vision system of a household kitchen assistant. This is a photo of a {kind}. "
        "List the distinct FOOD items you can actually see. Rules: use plain generic grocery names (e.g. 'chicken thighs', 'milk', 'spinach', 'pasta', 'eggs', 'yogurt'); "
        "never invent items you can't see; skip non-food objects; give an honest confidence 0-1 for each (<0.5 if blurry, partly hidden or guessed; an unidentifiable container is name 'unknown container' with confidence 0.2); "
        "quantity is a short human estimate like '1 gallon, half full' or 'about 6'; amount is one of full, plenty, some, low, almost_empty; "
        "freshness is one of fresh, ok, aging, spoiling, unknown - only judge from visible cues (wilting, browning, frost, dates), otherwise unknown; "
        "shelf is where it sits if clear; brand only if legible. Max 40 items. Also a 'note' saying anything notable (e.g. photo too dark).")
    parts = [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(image_bytes).decode()}}]
    res, model = generate(parts, ITEMS_SCHEMA, VISION_MODELS, timeout=45, temperature=0.2)
    items = res.get("items", [])
    for it in items:
        try:
            it["confidence"] = max(0.05, min(0.99, float(it.get("confidence", 0.6))))
        except Exception:
            it["confidence"] = 0.5
    return items, res.get("note", ""), model

# ---- simple per-client rate limit so a public URL can't burn the key
_hits = {}
_lock = threading.Lock()

def allow(client, limit=60, window=3600):
    now = time.time()
    with _lock:
        h = [t for t in _hits.get(client, []) if now - t < window]
        if len(h) >= limit:
            _hits[client] = h
            return False
        h.append(now)
        _hits[client] = h
        return True
