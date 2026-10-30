// node tests/links.mjs [baseUrl]  - checks the Shopping tab's store links and Copy list
import puppeteer from "/workspace/pptr/node_modules/puppeteer-core/lib/esm/puppeteer/puppeteer-core.js";
const BASE = process.argv[2] || "http://localhost:8000";
const b = await puppeteer.launch({ executablePath: "/usr/bin/google-chrome", args: ["--no-sandbox"] });
const p = await b.newPage();
await p.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await p.goto(BASE, { waitUntil: "networkidle0" });
await p.evaluate(async () => {
  const s = (await (await fetch("/api/demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" })).json()).state;
  s.setup_done = true; s.members = [{ id: "a", name: "Mellow", allergies: [], diets: [] }];
  localStorage.setItem("kitchenos.v1", JSON.stringify(s));
});
await p.reload({ waitUntil: "networkidle0" });
await p.evaluate(async () => { for (const m of ["add milk to the shopping list", "add paper towels to the shopping list", "add half & half to the shopping list"]) setState((await api("assistant", { message: m })).state); ui.shop = null; });
await p.evaluate(() => go("shopping"));
await new Promise(r => setTimeout(r, 1500));
const rows = await p.evaluate(() => [...document.querySelectorAll(".item")].map(i => ({ name: i.querySelector("b").innerText, links: [...i.querySelectorAll("a.find")].map(a => ({ t: a.innerText, h: a.href, target: a.target, rel: a.rel })) })));
let bad = 0;
for (const r of rows) {
  const q = encodeURIComponent(r.name);
  const want = { Walmart: `https://www.walmart.com/search?q=${q}`, Publix: `https://www.publix.com/search?searchTerm=${q}`, Instacart: `https://www.instacart.com/store/s?k=${q}` };
  for (const l of r.links) if (l.h !== want[l.t] || l.target !== "_blank" || !l.rel.includes("noopener")) { bad++; console.log("BAD", r.name, l); }
  if (r.links.length !== 3) { bad++; console.log("BAD count", r.name); }
}
console.log("items", rows.length, "bad", bad, "sample", JSON.stringify(rows[0]));
// a link really opens a new tab at the right URL
const tabP = new Promise(res => b.once("targetcreated", t => res(t)));
await p.evaluate(() => document.querySelector("a.find").click());
const tab = await tabP; await new Promise(r => setTimeout(r, 2500));
console.log("new tab url:", tab.url(), "(Walmart may show its bot-check page to headless Chrome; the url param encodes the search)");
for (const pg of await b.pages()) if (pg !== p) await pg.close().catch(() => {});
// copy list
await p.bringToFront();
await p.evaluate(() => { window.__c = null; Object.defineProperty(navigator, "clipboard", { value: { writeText: async t => { window.__c = t; } }, configurable: true }); });
await p.evaluate(() => document.querySelector("#copy").click());
await new Promise(r => setTimeout(r, 400));
console.log("copied:\n" + (await p.evaluate(() => window.__c)));
const send = await p.evaluate(() => ({ mail: document.querySelector("#mail").href, sms: document.querySelector("#sms").href, share: !!document.querySelector("#share") }));
console.log("mail:", decodeURIComponent(send.mail).replace(/\n/g, "|"));
console.log("sms:", decodeURIComponent(send.sms).replace(/\n/g, "|"));
if (!send.mail.startsWith("mailto:?subject=Shopping%20list&body=") || !/^sms:[&?]body=/.test(send.sms)) { console.log("BAD send links"); process.exit(1); }
await p.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); await new Promise(r => setTimeout(r, 3200));
await p.screenshot({ path: "shots/shopping-links.png" });
await b.close();
process.exit(bad ? 1 : 0);
