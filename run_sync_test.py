import httpx, json

with httpx.stream("POST", "http://localhost:8000/sync/start",
                  json={"repo_path": "data/test_md", "force_full": True}, timeout=600) as r:
    for line in r.iter_lines():
        if not line.strip() or not line.startswith("data: "):
            continue
        try:
            ev = json.loads(line[6:])
        except Exception:
            continue
        t = ev.get("type")
        if t in ("doc_indexed", "connector_done", "done", "error", "cancelled", "connector_error"):
            print(t, {k: v for k, v in ev.items() if k != "type"})
        if t in ("done", "error", "cancelled", "connector_error"):
            break
