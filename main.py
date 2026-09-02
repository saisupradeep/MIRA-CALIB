import asyncio
import json
import os
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from modbus_service import modbus_service

app = FastAPI(
    title="BridgeThings Modbus Web Application",
    description="Section 1 Meter Telemetry & Live Activity Logs - Mobile and Desktop Ready",
    version="1.0.0"
)

# Enable CORS for cross-origin mobile/laptop requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Mount static assets
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --- Request Models ---
class ConnectRequest(BaseModel):
    host: str = Field(default="192.168.1.100", description="IP Address or Domain of Modbus device")
    port: int = Field(default=502, ge=1, le=65535, description="Port number")
    slave_id: int = Field(default=1, ge=1, le=247, description="Modbus Slave / Unit ID")
    conn_type: str = Field(default="TCP", description="'TCP' or 'Telnet (RTU over TCP)'")
    simulation: bool = Field(default=False, description="Enable Simulation Mode for testing")

class SecretCodeRequest(BaseModel):
    code: str = Field(default="", description="Secret Code (e.g., 0xDCBA for Sec 1 Write, 0xABCD for Calib, or 0)")

class Section1WriteRequest(BaseModel):
    flowRate: str = Field(..., description="Flow Rate in m³/h")
    totalVolume64: str = Field(..., description="Total Volume 64-bit in m³")
    tempVal: str = Field(..., description="Temp Val (Reg 2-3)")
    fwdVolume: str = Field(..., description="Forward Volume in m³")
    revVolume: str = Field(..., description="Reverse Volume in m³")
    pumpMins: str = Field(..., description="Pump Running in mins")
    signal: str = Field(..., description="Signal Strength in dBm")

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>BridgeThings Modbus Web App</h1><p>Static files loading...</p>")

@app.get("/api/status")
async def get_status():
    return await asyncio.to_thread(modbus_service.get_status)

@app.post("/api/connect")
async def connect(req: ConnectRequest):
    result = await asyncio.to_thread(
        modbus_service.connect,
        host=req.host,
        port=req.port,
        slave_id=req.slave_id,
        conn_type=req.conn_type,
        simulation=req.simulation
    )
    if result.get("status") == "error":
        return JSONResponse(status_code=400, content=result)
    return result

@app.post("/api/disconnect")
async def disconnect():
    return await asyncio.to_thread(modbus_service.disconnect)

@app.get("/api/section1/read")
async def read_section1():
    result = await asyncio.to_thread(modbus_service.read_section1)
    if result.get("status") == "error":
        return JSONResponse(status_code=400, content=result)
    return result

@app.post("/api/section1/write")
async def write_section1(req: Section1WriteRequest):
    result = await asyncio.to_thread(modbus_service.write_section1, req.model_dump())
    if result.get("status") == "error":
        return JSONResponse(status_code=400, content=result)
    return result

@app.post("/api/secret")
async def write_secret(req: SecretCodeRequest):
    result = await asyncio.to_thread(modbus_service.write_secret_code, req.code)
    if result.get("status") == "error":
        return JSONResponse(status_code=400, content=result)
    return result

@app.get("/api/logs/history")
async def get_log_history():
    with modbus_service.lock:
        return {"logs": list(modbus_service.logs)}

@app.post("/api/logs/clear")
async def clear_logs():
    modbus_service.clear_logs()
    return {"status": "success", "message": "Logs cleared"}

@app.get("/api/logs/stream")
async def stream_logs(request: Request):
    """Server-Sent Events (SSE) streaming real-time logs to browser clients."""
    queue = asyncio.Queue()
    modbus_service.add_log_listener(queue)

    async def event_generator():
        try:
            # Yield existing recent logs first
            with modbus_service.lock:
                for log_item in modbus_service.logs[-30:]:
                    yield f"data: {json.dumps(log_item)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    log_item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(log_item)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping
                    yield ": ping\n\n"
        finally:
            modbus_service.remove_log_listener(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
