import os, sys
os.environ["LLM_API_KEY"] = ""  # tests never call the network
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app import model, engine, assistant, kb
from app.main import app

T = "2026-10-29"  # a Thursday

def kitchen(members=None, items=()):
    s = model.new_state()
    s["members"] = members or [{"name": "A", "allergies": [], "diets": [], "kid": False}]
    for name, loc, conf, fresh in items:
        s["items"].append(model.make_item(name, loc, T, conf=conf, level=0.8, freshness=fresh))
    return s

BASIC = [("pasta", "pantry", .9, "ok"), ("pasta sauce", "pantry", .9, "ok"), ("rice", "pantry", .9, "ok"), ("eggs", "fridge", .9, "ok"),
         ("soy sauce", "pantry", .9, "ok"), ("bread", "pantry", .8, "ok"), ("cheddar", "fridge", .9, "ok")]

# ---------------------------------------------------------------- kitchen model
def test_item_fields_and_probabilistic_enrichment():
    s = kitchen(items=[("spinach", "fridge", .7, "aging")])
    it = s["items"][0]
    for f in ("name", "observed", "purchased", "level", "qty_text", "conf"):
        assert f in it
    e = model.enrich_item(it, T)
    assert 0 <= e["spoilage_risk"] <= 1 and 0 <= e["consumption_probability"] <= 1
    assert e["tier"] in ("use_soon", "use_week")

def test_confidence_decays_without_new_observation():
    s = kitchen(items=[("milk", "fridge", .9, "fresh")])
    now = model.enrich_item(s["items"][0], T)["conf_now"]
    later = model.enrich_item(s["items"][0], "2026-11-05")["conf_now"]
    assert later < now < 0.91

def test_spoilage_risk_rises_with_age_and_chicken_is_urgent():
    old = model.enrich_item(model.make_item("chicken thighs", "fridge", T, freshness="aging"), T)
    fresh = model.enrich_item(model.make_item("chicken thighs", "fridge", T, freshness="fresh"), T)
    assert old["spoilage_risk"] > fresh["spoilage_risk"]
    assert old["tier"] == "use_soon"
    rice = model.enrich_item(model.make_item("rice", "pantry", T), T)
    assert rice["tier"] == "low"

def test_frozen_items_are_low_risk_in_freezer():
    e = model.enrich_item(model.make_item("chicken breast", "freezer", T), T)
    assert e["spoilage_risk"] < 0.1

# ---------------------------------------------------------------- ranking
def test_expiring_items_rank_first():
    # Same pantry; chicken is aging (use soon), ground beef is fresh. Both would make a fine dinner.
    s = kitchen(items=BASIC + [("chicken thighs", "fridge", .9, "aging"), ("broccoli", "fridge", .8, "ok"), ("ground beef", "fridge", .9, "fresh")])
    t = engine.tonight(s, T)
    names = [u["name"] for u in t["meal"]["uses"]]
    assert "Chicken thighs" in names
    assert t["use_soon"][0]["name"] == "Chicken thighs"

def test_use_up_statement_changes_pick():
    s = kitchen(items=BASIC + [("spinach", "fridge", .9, "ok"), ("ground beef", "fridge", .9, "ok"), ("tortillas", "pantry", .9, "ok"), ("cheddar", "fridge", .9, "ok")])
    assistant.handle(s, "use up spinach", T)
    t = engine.tonight(s, T)
    assert any(u["key"] == "spinach" for u in t["meal"]["uses"])

def test_every_recommendation_has_checked_against_and_verify_note():
    s = kitchen(members=[{"name": "A", "allergies": ["peanuts"], "diets": []}, {"name": "B", "allergies": [], "diets": ["vegetarian"]}], items=BASIC)
    t = engine.tonight(s, T)
    assert [c["name"] for c in t["meal"]["checked"]] == ["A", "B"]
    assert "verify labels" in t["verify_note"].lower()
    assert "safe" not in " ".join(c["note"] for c in t["meal"]["checked"]).lower()

# ---------------------------------------------------------------- allergy filtering
def test_allergy_filtering_never_recommends_conflicts():
    items = BASIC + [("peanut butter", "pantry", .9, "ok"), ("bananas", "pantry", .9, "ok"), ("heavy cream", "fridge", .9, "ok"),
                     ("parmesan", "fridge", .9, "ok"), ("chicken breast", "fridge", .9, "aging"), ("shrimp", "fridge", .9, "aging"), ("pesto", "fridge", .9, "ok")]
    for allergy, banned in [("peanuts", {"peanut butter"}), ("dairy", {"heavy cream", "parmesan", "cheddar", "pesto", "butter"}),
                            ("shellfish", {"shrimp"}), ("gluten", {"pasta", "bread", "tortillas", "soy sauce", "noodles"}), ("tree nuts", {"pesto", "almonds"}),
                            ("egg", {"eggs", "mayo"}), ("soy", {"soy sauce", "tofu"})]:
        s = kitchen(members=[{"name": "A", "allergies": [allergy], "diets": []}], items=items)
        for c in engine.rank(s, T, min_cov=0.0, max_missing=6) + engine.rank(s, T, dinner_only=False, types=["lunch"], min_cov=0.0, max_missing=6):
            planned = {e["key"] for e in c["used"] + c["extras"]} | set(c["missing"])
            assert not (planned & banned), (allergy, c["meal"]["name"], planned & banned)

def test_diet_filtering():
    items = BASIC + [("chicken breast", "fridge", .9, "aging"), ("ground beef", "fridge", .9, "aging"), ("broccoli", "fridge", .9, "ok"), ("black beans", "pantry", .9, "ok"), ("tortillas", "pantry", .9, "ok")]
    s = kitchen(members=[{"name": "V", "allergies": [], "diets": ["vegan"]}], items=items)
    for c in engine.rank(s, T, min_cov=0.0, max_missing=6):
        keys = {e["key"] for e in c["used"] + c["extras"]} | set(c["missing"])
        assert not any("animal" in kb.flags_of(k) or "meat" in kb.flags_of(k) or kb.allergens_of(k) & {"dairy", "egg", "fish"} for k in keys), c["meal"]["name"]

def test_household_all_members_must_be_ok():
    items = BASIC + [("chicken breast", "fridge", .9, "aging"), ("heavy cream", "fridge", .9, "ok"), ("parmesan", "fridge", .9, "ok")]
    s = kitchen(members=[{"name": "A", "allergies": [], "diets": []}, {"name": "B", "allergies": ["dairy"], "diets": []}], items=items)
    assert all(c["meal"]["id"] != "chicken_alfredo" for c in engine.rank(s, T, min_cov=0.0, max_missing=6))

# ---------------------------------------------------------------- freezer
def test_frozen_meat_not_for_tonight_but_nudged_for_tomorrow():
    s = kitchen(items=[("pasta", "pantry", .9, "ok"), ("chicken breast", "freezer", .9, "ok"), ("heavy cream", "fridge", .9, "ok"), ("parmesan", "fridge", .9, "ok"), ("eggs", "fridge", .9, "ok"), ("bread", "pantry", .9, "ok")])
    t = engine.tonight(s, T)
    assert all(u["location"] != "freezer" for u in t["meal"]["uses"])
    nudge = engine.freezer_nudge(s, T, t["_c"])
    assert nudge and "freezer to the fridge tonight" in nudge["text"]

# ---------------------------------------------------------------- assistant
def test_assistant_used_all_add_and_use_up():
    s = kitchen(items=BASIC + [("yogurt", "fridge", .9, "ok"), ("spinach", "fridge", .6, "aging")])
    r = assistant.handle(s, "we used all the yogurt", T)
    assert [i for i in s["items"] if i["key"] == "yogurt"][0]["level"] == 0
    assert "Yogurt" in " ".join(r["changes"])
    assistant.handle(s, "add milk", T)
    milk = [i for i in s["items"] if i["key"] == "milk"][0]
    assert milk["level"] == 1.0 and milk["purchased"] == T
    assistant.handle(s, "use up spinach", T)
    assert "spinach" in s["use_up"]
    assistant.handle(s, "we need paper towels", T)
    assert any("paper towels" in x["name"] for x in s["shopping"])

def test_assistant_unknown_phrase_degrades_gracefully_without_ai():
    s = kitchen(items=BASIC)
    r = assistant.handle(s, "tell me a story about trains", T)
    assert r["source"] == "fallback" and r["reply"]

def test_shopping_has_three_categories_and_flags_used_up_staples():
    s = kitchen(items=BASIC + [("milk", "fridge", .9, "ok")])
    assistant.handle(s, "we're out of milk", T)
    sh = engine.shopping(s, T)
    assert set(sh) == {"need_soon", "running_low", "recommended"}
    assert any(x["key"] == "milk" for x in sh["running_low"] + sh["need_soon"])

def test_week_plan_has_seven_days_and_varied_meals():
    s = kitchen(items=BASIC + [("chicken thighs", "fridge", .9, "aging"), ("spinach", "fridge", .8, "ok"), ("broccoli", "fridge", .8, "ok")])
    w = engine.week_plan(s, T)["plan"]
    assert len(w) == 7
    ids = [p["meal_id"] for p in w]
    assert len(set(ids)) >= 5

# ---------------------------------------------------------------- API (AI off -> heuristic fallback)
def test_api_end_to_end_without_ai():
    c = TestClient(app)
    assert c.get("/api/health").json()["ai"] is False
    st = c.post("/api/demo", json={"today": T, "state": {"members": [{"id": "1", "name": "Mellow", "allergies": ["peanuts"], "diets": []}]}}).json()["state"]
    t = c.post("/api/tonight", json={"state": st, "today": T}).json()["tonight"]
    assert t["meal"]["name"] and t["meal"]["reasons"] and t["meal"]["checked"][0]["name"] == "Mellow"
    r = c.post("/api/tonight/action", json={"state": st, "today": T, "action": "alternate", "meal_id": t["meal"]["id"]}).json()
    assert r["tonight"]["meal"]["id"] != t["meal"]["id"]
    ex = c.post("/api/explain", json={"state": st, "today": T}).json()
    assert ex["source"] == "rules" and "verify labels" in ex["text"].lower()
    assert len(c.post("/api/week", json={"state": st, "today": T}).json()["plan"]) == 7
    assert set(c.post("/api/shopping", json={"state": st, "today": T}).json()["shopping"]) == {"need_soon", "running_low", "recommended"}

def test_pwa_files_served():
    c = TestClient(app)
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone"
    for p in ("/icon-180.png", "/icon-192.png", "/icon-512.png", "/apple-touch-icon.png", "/sw.js"):
        assert c.get(p).status_code == 200, p
    assert "apple-touch-icon" in c.get("/").text


def test_guide_page_served():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/guide")
    assert r.status_code == 200 and "Created by" in r.text and "Add to Home Screen" in r.text
    assert c.get("/kitchen-os-logo-1024.png").status_code == 200
