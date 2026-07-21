import httpx, time, json

for i in range(60):
    try:
        s = httpx.get("http://localhost:8000/sync/status", timeout=10).json()
    except Exception as e:
        print("status err", e)
        break
    print(i * 15, "indexing=", s["indexing"], "rows=", s["total_rows"], "repos=", s["repos"])
    if not s["indexing"] and s["last_result"] is not None:
        print("DONE:", json.dumps(s["last_result"])[:500])
        break
    time.sleep(15)
