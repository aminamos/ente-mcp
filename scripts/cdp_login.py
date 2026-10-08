"""Drive etne museum login over CDP (headless). No secrets written to disk.

Reads ETNE_EMAIL / ETNE_PW from env. Steps:
1. Clear official-cloud auth state (localStorage + KV token + session).
2. Set KV apiOrigin to the museum.
3. Navigate to ente://app/ and walk the login form (email -> password).
4. Poll for an authenticated session.
"""
import json
import os
import sys
import time
import urllib.request

import websocket

EMAIL = os.environ.get("ETNE_EMAIL", "")
PASSWORD = os.environ.get("ETNE_PW", "")
MUSEUM = "https://etne.robusteland.box.ca"
if not EMAIL or not PASSWORD:
    sys.exit("need ETNE_EMAIL and ETNE_PW env")

tabs = json.load(urllib.request.urlopen("http://localhost:9333/json"))
pages = [t for t in tabs if t["type"] == "page"]
if not pages:
    sys.exit("no page target")
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)
seq = [0]


def send(method, params=None):
    seq[0] += 1
    ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
    return seq[0]


def recv(mid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg
    raise TimeoutError(f"cdp {mid} timeout")


def ev(expr, timeout=90):
    mid = send("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                    "returnByValue": True})
    r = recv(mid, timeout)
    res = r.get("result", {}).get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description", "js error")[:500])
    return res.get("value")


print("1. clearing official auth + setting museum endpoint...", flush=True)
print(ev("""
(async () => {
  for (const k of ['user','keyAttributes','srpAttributes','remoteFeatureFlags'])
    localStorage.removeItem(k);
  sessionStorage.clear();
  const db = await new Promise((res, rej) => {
    const r = indexedDB.open('kv', 1);
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  const tx = db.transaction('kv', 'readwrite');
  await new Promise((res, rej) => {
    const d = tx.objectStore('kv').delete('token');
    d.onsuccess = res; d.onerror = () => rej(d.error);
  });
  await new Promise((res, rej) => {
    const p = tx.objectStore('kv').put('""" + MUSEUM + """', 'apiOrigin');
    p.onsuccess = res; p.onerror = () => rej(p.error);
  });
  db.close();
  return 'cleared+endpoint-set';
})()
"""), flush=True)

print("2. navigating to app root...", flush=True)
mid = send("Page.navigate", {"url": "ente://app/"})
recv(mid)
time.sleep(6)

SETFILL = """
(window.__fill = window.__fill || ((sel, v) => {
  const el = document.querySelector(sel);
  if (!el) return 'missing:' + sel;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
                                          : HTMLInputElement.prototype;
  const d = Object.getOwnPropertyDescriptor(proto, 'value');
  d.set.call(el, v);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return 'filled:' + sel;
}))
"""

CLICKTEXT = """
((texts) => {
  const els = [...document.querySelectorAll('button,a,[role="button"]')];
  for (const t of texts) {
    const m = els.find(e => (e.innerText || '').trim().toLowerCase().includes(t));
    if (m) { m.click(); return 'clicked:' + t; }
  }
  return 'noclick';
})
"""

print("3. walking login form (up to 3 min)...", flush=True)
deadline = time.time() + 180
last_state = ""
while time.time() < deadline:
    state = ev("""
(() => {
  const email = document.querySelector('input[type="email"],input[name="email"],input[autocomplete="email"]');
  const pass = document.querySelector('input[type="password"]');
  const totp = document.querySelector('input[name="totp"],input[autocomplete="one-time-code"]');
  const btns = [...document.querySelectorAll('button')].map(b => (b.innerText||'').trim().slice(0,24)).filter(Boolean).slice(0,6);
  return {url: location.href.slice(0,60), email: !!email, pass: !!pass, totp: !!totp,
          user: !!localStorage.getItem('user'), btns,
          body: document.body.innerText.slice(0,200).replace(/\\n/g,' | ')};
})()
""")
    sig = json.dumps(state)
    if sig != last_state:
        print("  state:", sig[:300], flush=True)
        last_state = sig
    if state.get("user"):
        u = ev("localStorage.getItem('user').slice(0,120)")
        print("  LOGGED IN:", u, flush=True)
        break
    if state.get("totp"):
        print("  NEED-TOTP: account wants a 2FA code", flush=True)
        break
    ev(SETFILL)
    if state.get("email"):
        ev(f"window.__fill('input[type=\"email\"],input[name=\"email\"]', {json.dumps(EMAIL)})")
        time.sleep(1)
        print("  " + ev(CLICKTEXT + "(['continue','next','log in','login'])"), flush=True)
        time.sleep(4)
        continue
    if state.get("pass"):
        ev("window.__fill('input[type=\"password\"]', " + json.dumps(PASSWORD) + ")")
        time.sleep(1)
        print("  " + ev(CLICKTEXT + "(['log in','login','continue','verify'])"), flush=True)
        time.sleep(5)
        continue
    # Welcome/chooser screen?
    clicked = ev(CLICKTEXT + "(['log in','login','existing','i have'])")
    if clicked != "noclick":
        print("  " + clicked, flush=True)
        time.sleep(4)
        continue
    time.sleep(4)
else:
    print("  TIMEOUT waiting for login", flush=True)

print("4. final session check...", flush=True)
print(ev("""
(() => ({user: (localStorage.getItem('user')||'').slice(0,150),
          url: location.href.slice(0,80)}))()
"""), flush=True)
ws.close()
