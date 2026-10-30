import os, re
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
B = "https://kitchen-os-am7y.onrender.com"

def test_share_image_served():
    r = c.get("/share-card.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n" and len(r.content) < 1_000_000

def test_social_tags_on_pages():
    for path in ("/", "/guide", "/about"):
        h = c.get(path).text
        for t in ('property="og:type" content="website"', 'property="og:image" content="%s/share-card.png"' % B,
                  'property="og:image:width" content="1200"', 'property="og:image:height" content="630"',
                  'name="twitter:card" content="summary_large_image"', 'name="twitter:image" content="%s/share-card.png"' % B,
                  'property="og:image:alt"', 'name="twitter:image:alt"', 'property="og:url"', 'name="twitter:title"'):
            assert t in h, (path, t)
