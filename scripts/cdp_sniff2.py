import json, time, urllib.request, websocket

tabs = json.load(urllib.request.urlopen("http://localhost:9333/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=100)
seq = [0]
def send(method, params=None):
    seq[0] += 1
    ws.send(json.dumps({"id": seq[0], "method": method, "params": params or {}}))
send("Network.enable")
end = time.time() + 80
seen = {}
n = 0
while time.time() < end and n < 30:
    try:
        msg = json.loads(ws.recv())
    except Exception:
        break
    m = msg.get("method")
    if m == "Network.requestWillBeSent":
        p = msg["params"]["request"]
        url = p.get("url", "")
        if "stream://" in url:
            continue
        host = url.split("/")[2] if "://" in url else url[:30]
        print("REQ", p.get("method"), host, url[url.index(host)+len(host):][:70])
        seen[msg["params"]["requestId"]] = url[:60]
        n += 1
    elif m == "Network.responseReceived":
        rid = msg["params"]["requestId"]
        if rid in seen:
            p = msg["params"]["response"]
            print("  ->", p.get("status"), p.get("url", "")[:60])
    elif m == "Network.loadingFailed":
        rid = msg["params"]["requestId"]
        if rid in seen:
            print("  FAIL", msg["params"].get("errorText"), seen.pop(rid))
ws.close()
