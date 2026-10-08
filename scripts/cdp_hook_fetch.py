import json, urllib.request, websocket

tabs = json.load(urllib.request.urlopen("http://localhost:9333/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)

def ev(i, expr):
    ws.send(json.dumps({"id": i, "method": "Runtime.evaluate",
        "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == i:
            return msg["result"]

# Hook fetch for the next upload attempt, then trigger one via the app if possible.
# Wrap fetch, capture request URL + method, and error message for 90s.
r = ev(1, """
(async () => {
  window.__fetchLog = [];
  const orig = window.fetch;
  window.fetch = async (...args) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url;
    const method = args[1]?.method || 'GET';
    try {
      const res = await orig(...args);
      window.__fetchLog.push({url, method, status: res.status});
      return res;
    } catch (e) {
      window.__fetchLog.push({url, method, error: String(e)});
      throw e;
    }
  };
  window.__fetchHooked = true;
  return 'hooked';
})()
""")
print("hook:", r["result"]["value"])

# Wait, then read the log + apiOrigin + token presence
import time
time.sleep(45)
r = ev(2, """
(async () => {
  const entries = window.__fetchLog || [];
  return {count: entries.length, entries: entries.slice(-25)};
})()
""")
print(json.dumps(r, indent=2)[:4000])
ws.close()
