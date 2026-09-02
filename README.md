# BridgeThings Modbus Hub — Section 1 & Live Logs

A responsive web application for remote Modbus meter monitoring and configuration, focused specifically on **Section 1 (Meter Readings)** and **Real-Time Activity Logs**.

Designed for access across **mobile phones** and **laptop browsers** over the internet, and ready for one-click deployment on **Render** from **GitHub**.

---

## 🌟 Key Features

- **Section 1 Telemetry Dashboard**:
  - **Flow Rate** ($m^3/h$) — Reg 0–1 (Float32)
  - **Total Volume 64-bit** ($m^3$) — Reg 12–15 (Float64)
  - **Forward Volume** ($m^3$) — Reg 4–5 (Float32)
  - **Reverse Volume** ($m^3$) — Reg 6–7 (Float32)
  - **Pump Running Time** ($mins$) — Reg 8–9 (Float32)
  - **Signal Strength** ($dBm$) — Reg 10–11 (Float32)
  - **Temp Val** — Reg 2–3 (Float32)
  - **Tamper Status** — Reg 44 (Uint16)
- **Live Terminal Activity Logs**: Real-time Server-Sent Events (SSE) streaming of Modbus operations, status codes, timestamps, filtering, auto-scroll, and export as `.txt`.
- **Auto-Polling Mode**: Configurable live telemetry refresh intervals (1s, 2s, 5s, 10s).
- **Security & Write Permission Handling**:
  - Unlocks via Secret Code `0xDCBA` for Section 1 writing.
  - Safe pre-populated Section 1 writing modal with confirmation checks.
- **Protocol Flexibility**: Supports direct **Modbus TCP**, **Telnet (RTU over TCP)**, and a realistic **Demo / Simulation Mode** for immediate testing without physical hardware.

---

## 🚀 Quick Start (Running Locally on Laptop)

### 1. Install Dependencies
```bash
py -m pip install -r requirements.txt
```

### 2. Start the Web Server
```bash
py main.py
```
Or with uvicorn:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open in Browser
- On your laptop: Open `http://localhost:8000`
- On your mobile phone (on same Wi-Fi): Open `http://<your-laptop-ip>:8000` (e.g. `http://192.168.1.50:8000`)

---

## ☁️ Deploying to Render via GitHub (Free Hosting)

### Step 1: Create a GitHub Repository
1. Go to [github.com/new](https://github.com/new) and create a repository (e.g. `modbus-section1-hub`).
2. In your terminal inside this project folder (`scratch/modbus-web-app`):
```bash
git init
git add .
git commit -m "Initial commit: Modbus Section 1 web application"
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/modbus-section1-hub.git
git push -u origin main
```

### Step 2: Deploy on Render.com
1. Log into [dashboard.render.com](https://dashboard.render.com/).
2. Click **New +** → Select **Web Service**.
3. Connect your GitHub account and select the repository (`modbus-section1-hub`).
4. Set the following options (Render auto-detects these from `render.yaml` / `Procfile`):
   - **Name**: `modbus-meter-hub`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
5. Click **Deploy Web Service**.
6. In ~1 minute, Render provides you with a live HTTPS link (e.g. `https://modbus-meter-hub.onrender.com`).

---

## 📱 Accessing from Mobile and Laptop over the Internet

Once deployed to Render:
1. Open your Render HTTPS URL on any **mobile phone** or **laptop**.
2. **Connecting to your Meter**:
   - **If using Simulation Mode**: Check **Demo / Simulation Mode** and click **Connect**. You can immediately test reading, secret unlocking (`0xDCBA`), writing Section 1, auto-polling, and live logs.
   - **If connecting to a physical meter over internet**:
     - Provide the public IP or Dynamic DNS hostname of your network where the meter is connected (e.g. `203.0.113.45` or `mymeter.ddns.net`) with port `502` forwarded to the meter's IP on your router.
     - Alternatively, use a secure tunnel such as **Tailscale**, **ZeroTier**, or **ngrok** (`ngrok tcp 502`) to securely expose your meter to your cloud app.

---

## 📁 Project Structure

```
modbus-web-app/
├── main.py                # FastAPI REST API & SSE Server
├── modbus_service.py      # Modbus client engine, register mapping & simulation
├── static/
│   ├── index.html         # Responsive HTML5 UI (Mobile & Laptop)
│   ├── style.css          # Glassmorphic dark design system
│   └── app.js             # Client controller, SSE listener & auto-poll
├── requirements.txt       # Python dependencies
├── render.yaml            # Render deployment blueprint
├── Procfile               # Render startup process
├── .gitignore
└── README.md
```
