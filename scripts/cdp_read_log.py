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

r = ev(1, "(window.__fetchLog || []).slice(-30)")
print(json.dumps(r, indent=2)[:4000])
ws.close()
