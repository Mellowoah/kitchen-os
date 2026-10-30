# Kitchen OS (prototype)

A decision engine for "what are we eating tonight?" - not a pantry tracker. Snap fridge / freezer / pantry photos once; the **Tonight** tab gives one meal with *why it was selected*, *Checked against* (every household member) and *Need to buy*.

Tabs: Tonight · This Week · Shopping (Need Soon / Running Low / Recommended) · Assistant ("we used all the yogurt", "add milk", "use up spinach"...).

## Stack
FastAPI (`app/`) serving a mobile-first vanilla-JS PWA (`static/`). No database: the kitchen model lives in the phone's localStorage and is sent with each request; the server is stateless. Photos are analyzed and discarded.

- `app/model.py` - Kitchen Memory Engine (per item: name, observed date, purchase date, estimated quantity, confidence, spoilage risk, consumption probability)
- `app/engine.py` - dinner ranking (waste first), week plan, shopping, freezer nudge
- `app/assistant.py` - rule-based understanding first, Gemini fallback
- `app/ai.py` - Gemini vision + text, server-side only
- `app/kb.py`, `app/meals.py` - small food knowledge base (shelf life, allergens, diet flags) and 44-meal library

## AI
`LLM_API_KEY` (Google Gemini API key) is read from the environment only. Vision: `gemini-3.5-flash` (falls back to `-flash-lite`). If the key is missing or a call fails, everything still works: ranking is heuristic, the assistant uses its rules, photos can be replaced by "What did we miss?" chat or the sample kitchen.

## Mocked / stubbed
Receipt OCR, hardware cameras, real prices (rough estimates), weather. Marked DEMO in the UI.

## Safety
Allergy/diet checks use general food knowledge, never product labels. The app never claims a meal is safe and always shows a "verify labels" note.

## Run
```
pip install -r requirements-dev.txt
LLM_API_KEY=... uvicorn app.main:app --reload
pytest
```
