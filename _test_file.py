import urllib.request
base = "http://127.0.0.1:8765"

try:
    req = urllib.request.Request(base + "/file?path=test3.md")
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode()
        print("Status:", resp.status)
        print("Length:", len(html))
        print("Has title:", "test3.md" in html)
        print("Has content:", "Vector Databases" in html)
        print("Has line numbers:", 'class="ln"' in html)
except Exception as e:
    print("ERROR:", e)

try:
    req2 = urllib.request.Request(base + "/file?path=../.env")
    with urllib.request.urlopen(req2, timeout=10) as resp:
        print("PATH TRAVERSAL: should not happen")
except urllib.error.HTTPError as e:
    print("Path traversal blocked:", e.code)

try:
    req3 = urllib.request.Request(base + "/file")
    with urllib.request.urlopen(req3, timeout=10) as resp:
        print("Missing path: should not happen")
except urllib.error.HTTPError as e:
    print("Missing path returns:", e.code)

print("ALL OK")
