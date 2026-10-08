"""Submit museum password on the credentials page, wait for full session."""
import json
import os
import sys
import time
import urllib.request

import websocket

PASSWORD = os.environ.get("ETNE_PW", "")
if not PASSWORD:
    sys.exit("need ETNE_PW env")

tabs = json.load(urllib.request.urlopen("http://localhost:9333/json"))
pages = [t for t in tabs if t["type"] == "page"]
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)
seq = [0]


def send(method, params=None):
    seq[0] += 1
    ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
    return seq[0]


def recv(mid, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        msg = json.loads(ws.recv())
        if msg.get("id") == mid:
            return msg
    raise TimeoutError("cdp timeout")


def ev(expr, timeout=120):
    mid = send("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                    "returnByValue": True})
    r = recv(mid, timeout)
    res = r.get("result", {}).get("result", {})
    if res.get("subtype") == "error":
        raise RuntimeError(res.get("description", "js error")[:500])
    return res.get("value")


print(ev("""
(() => ({url: location.href,
         pass: !!document.querySelector('input[type="password"]'),
         user: (localStorage.getItem('user')||'none').slice(0,120)}))()
"""), flush=True)

ev("""
((v) => {
  const el = document.querySelector('input[type="password"]');
  const d = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  d.set.call(el, v);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return 'filled';
})(""" + json.dumps(PASSWORD) + ")")
time.sleep(1)
print(ev("""
(() => {
  const els = [...document.querySelectorAll('button')];
  const m = els.find(e => /sign in|log in|continue|verify/i.test(e.innerText||''));
  if (m) { m.click(); return 'clicked:' + m.innerText.trim().slice(0,20); }
  const f = document.querySelector('form');
  if (f) { f.requestSubmit(); return 'submitted-form'; }
  return 'noclick';
})()
"""), flush=True)

end = time.time() + 120
while time.time() < end:
    s = ev("""
(() => {
  let u = {};
  try { u = JSON.parse(localStorage.getItem('user') || '{}'); } catch(e) {}
  const totp = !!document.querySelector('input[name="totp"],input[autocomplete="one-time-code"]');
  return {url: location.href.slice(0,60), id: u.id || null, email: u.email || null,
          token: !!localStorage.getItem('user') && !!document.cookie,
          totp, body: document.body.innerText.slice(0,150).replace(/\\n/g,'|')};
})()
""")
    print(" ", json.dumps(s)[:250], flush=True)
    if s.get("id") and s.get("email"):
        print("FULL SESSION OK", flush=True)
        break
    if s.get("totp"):
        print("NEED-TOTP", flush=True)
        break
    time.sleep(5)
ws.close()
