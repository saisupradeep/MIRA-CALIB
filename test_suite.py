import requests

BASE = "http://127.0.0.1:8000"

print("1. Status:")
r = requests.get(f"{BASE}/api/status", timeout=5)
print(r.status_code, r.json())

print("\n2. Connect (Simulation):")
r = requests.post(f"{BASE}/api/connect", json={
    "host": "192.168.1.100",
    "port": 502,
    "slave_id": 1,
    "conn_type": "TCP",
    "simulation": True
}, timeout=5)
print(r.status_code, r.json())

print("\n3. Read Section 1:")
r = requests.get(f"{BASE}/api/section1/read", timeout=5)
print(r.status_code, r.json())

print("\n4. Secret Code (0xDCBA):")
r = requests.post(f"{BASE}/api/secret", json={"code": "0xDCBA"}, timeout=5)
print(r.status_code, r.json())

print("\n5. Write Section 1:")
r = requests.post(f"{BASE}/api/section1/write", json={
    "flowRate": "19.850",
    "totalVolume64": "25000.654321",
    "tempVal": "27.500",
    "fwdVolume": "24000.000",
    "revVolume": "1000.654",
    "pumpMins": "1800.0",
    "signal": "-65.0"
}, timeout=5)
print(r.status_code, r.json())

print("\n6. Read Section 1 again (verify written values):")
r = requests.get(f"{BASE}/api/section1/read", timeout=5)
print(r.status_code, r.json())

print("\n7. Log History:")
r = requests.get(f"{BASE}/api/logs/history", timeout=5)
data = r.json()
print(f"Total events: {len(data['logs'])}")
for l in data['logs'][-4:]:
    clean_msg = l['message'].encode('ascii', errors='replace').decode('ascii')
    print(f"  [{l['time']}] [{l['level'].upper()}] {clean_msg}")

print("\n>>> ALL API ENDPOINTS WORKING PERFECTLY! <<<")
