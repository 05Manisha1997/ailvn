import requests
res = requests.post("http://localhost:8000/tts", json={"text": "hello test"})
print(res.status_code)
print(res.headers)
print(len(res.content))
