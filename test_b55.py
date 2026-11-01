import urllib.request, json

req = urllib.request.Request("http://127.0.0.1:8000/books/55/enrich-spice", data=b"", headers={"Content-Type": "application/json"}, method="POST")
try:
    res = urllib.request.urlopen(req)
    print("Status:", res.status)
    data = json.loads(res.read().decode("utf-8"))
    print("Data:", data)
except Exception as e:
    print("Error:", e)
