"""Verify Test-Truck landed on the museum via authenticated API calls."""
import json
import urllib.request

import websocket

tabs = json.load(urllib.request.urlopen("http://localhost:9333/json"))
pages = [t for t in tabs if t["type"] == "page"]
ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"], timeout=60)
seq = [0]


def ev(expr, timeout=60):
    import time
    seq[0] += 1
    ws.send(json.dumps({"id": seq[0], "method": "Runtime.evaluate",
                        "params": {"expression": expr, "awaitPromise": True,
                                  "returnByValue": True}}))
    end = time.time() + timeout
    while time.time() < end:
        msg = json.loads(ws.recv())
        if msg.get("id") == seq[0]:
            res = msg.get("result", {}).get("result", {})
            if res.get("subtype") == "error":
                raise RuntimeError(res.get("description", "")[:300])
            return res.get("value")
    raise TimeoutError("cdp")


print(json.dumps(ev("""
(async () => {
  const keys = await (async () => {
    const db = await new Promise((res, rej) => {
      const r = indexedDB.open('kv', 1);
      r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
    });
    const tx = db.transaction('kv', 'readonly');
    const get = (k) => new Promise((res, rej) => {
      const g = tx.objectStore('kv').get(k);
      g.onsuccess = () => res(g.result); g.onerror = () => rej(g.error);
    });
    const out = {token: await get('token'), apiOrigin: await get('apiOrigin')};
    db.close();
    return out;
  })();
  const origin = keys.apiOrigin || 'https://api.ente.com';
  const hdrs = {'X-Auth-Token': keys.token, 'X-Client-Package': 'io.ente.photos.desktop'};
  const cols = await (await fetch(origin + '/collections', {headers: hdrs})).json();
  const summary = (cols.collections || cols || []).map(c => ({id: c.id, name: c.name || c.collectionName || '?'}));
  // file counts per collection via diff
  const out = {origin, collections: summary};
  for (const c of summary.slice(0, 10)) {
    try {
      const diff = await (await fetch(origin + '/collections/diff', {
        method: 'POST', headers: {...hdrs, 'Content-Type': 'application/json'},
        body: JSON.stringify({collectionID: c.id, sinceTime: 0})})).json();
      out[c.name] = (diff.diff || []).length;
    } catch (e) { out[c.name] = 'diff-failed:' + String(e).slice(0,60); }
  }
  return out;
})()
"""), indent=1)[:2000])
ws.close()
