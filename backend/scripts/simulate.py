import time, httpx
API = "http://localhost:8000/api/vitals"

def send(**kw):
    r = httpx.post(API, json={"seat_id": "CHAIR_01", **kw}, timeout=3)
    print(kw.get("breathing_pattern"), r.json())

for _ in range(5):
    send(resp_rate_bpm=16, breathing_pattern="normal", breathing_severity="normal", max_gap_s=3.0); time.sleep(1)
for _ in range(4):
    send(resp_rate_bpm=None, breathing_pattern="apnea", breathing_severity="critical", max_gap_s=12.0); time.sleep(1)
for _ in range(3):
    send(resp_rate_bpm=15, breathing_pattern="normal", breathing_severity="normal", max_gap_s=3.0); time.sleep(1)
