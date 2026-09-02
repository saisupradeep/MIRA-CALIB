import asyncio
import datetime
import logging
import random
import socket
import struct
import threading
import time
from typing import Dict, Any, Optional, List

try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    from pymodbus.payload import BinaryPayloadDecoder, BinaryPayloadBuilder
    from pymodbus.constants import Endian
    from pymodbus.exceptions import ModbusException, ConnectionException, ModbusIOException
except ImportError:
    ModbusTcpClient = None
    ModbusSerialClient = None
    BinaryPayloadDecoder = None
    BinaryPayloadBuilder = None
    Endian = None
    ModbusException = Exception

# --- Modbus Constants matching EFM32 Meter Firmware ---
SECRET_CODE_VALUE = 0xABCD           # Calibration Mode (43981)
SECRET_CODE_VALUE_SECTION1 = 0xDCBA  # Section 1 Write Mode (56506)

REG_FLOW_RATE_HIGH = 0               # float32 (Regs 0-1)
REG_FLOW_RATE_LOW = 1
REG_TEMP_VAL_HIGH = 2                # float32 (Regs 2-3)
REG_TEMP_VAL_LOW = 3
REG_FWD_VOLUME_HIGH = 4              # float32 (Regs 4-5)
REG_FWD_VOLUME_LOW = 5
REG_REV_VOLUME_HIGH = 6              # float32 (Regs 6-7)
REG_REV_VOLUME_LOW = 7
REG_PUMP_MINS_HIGH = 8               # float32 (Regs 8-9)
REG_PUMP_MINS_LOW = 9
REG_SIGNAL_STRENGTH_HIGH = 10        # float32 (Regs 10-11)
REG_SIGNAL_STRENGTH_LOW = 11
REG_TOTAL_VOLUME_64_ADDR_START = 12  # float64 (Regs 12-15)

REG_SECRET_CODE = 30                 # uint16 (Reg 30)
REG_COMMAND = 31                     # uint16 (Reg 31)
REG_TAMPER_STATUS = 44               # uint16 (Reg 44)

logger = logging.getLogger("modbus_service")

class ModbusService:
    def __init__(self):
        self.lock = threading.RLock()
        self.client = None
        self.is_connected = False
        self.is_simulation = False
        self.conn_type = "TCP"  # "TCP" or "Telnet (RTU over TCP)"
        self.host = "192.168.1.100"
        self.port = 502
        self.slave_id = 1
        self.section1_write_enabled = False
        self.calib_mode_active = False
        self.mode_status = "Mode: OFF"

        # Log buffer for web clients
        self.logs: List[Dict[str, Any]] = []
        self.log_listeners: List[asyncio.Queue] = []
        self._max_logs = 500

        # Cached simulation state
        self.sim_data = {
            "flowRate": 12.450,
            "totalVolume64": 15842.684120,
            "tempVal": 24.850,
            "fwdVolume": 14920.350,
            "revVolume": 922.334,
            "pumpMins": 1420.0,
            "signal": -74.5,
            "tamper": 0,
        }

        self.last_readings: Dict[str, Any] = {}
        self.log("info", "Modbus Service initialized and ready.")

    def log(self, level: str, message: str):
        """Append log message and notify all active SSE stream subscribers."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {
            "id": len(self.logs) + 1,
            "time": timestamp,
            "level": level.lower(),
            "message": message,
        }
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > self._max_logs:
                self.logs.pop(0)

        # Notify async queues
        for q in list(self.log_listeners):
            try:
                q.put_nowait(entry)
            except Exception:
                pass

    def add_log_listener(self, queue: asyncio.Queue):
        with self.lock:
            self.log_listeners.append(queue)

    def remove_log_listener(self, queue: asyncio.Queue):
        with self.lock:
            if queue in self.log_listeners:
                self.log_listeners.remove(queue)

    def clear_logs(self):
        with self.lock:
            self.logs.clear()
        self.log("info", "Status logs cleared.")

    def connect(self, host: str, port: int, slave_id: int, conn_type: str = "TCP", simulation: bool = False) -> Dict[str, Any]:
        with self.lock:
            if self.is_connected:
                self._disconnect_internal()

            self.host = host.strip()
            self.port = port
            self.slave_id = slave_id
            self.conn_type = conn_type
            self.is_simulation = simulation

            if self.is_simulation:
                self.is_connected = True
                self.log("success", f"[SIMULATION MODE] Connected to virtual Modbus meter at {self.host}:{self.port} (Unit ID: {self.slave_id}).")
                return {"status": "success", "message": f"Connected to simulated meter (Unit ID: {self.slave_id})"}

            self.log("info", f"Attempting {conn_type} connection to {self.host}:{self.port} (Slave ID: {self.slave_id})...")

            # Basic socket reachability test
            test_socket = None
            try:
                test_socket = socket.create_connection((self.host, self.port), timeout=4.0)
                self.log("info", f"--> TCP socket pre-check SUCCEEDED to {self.host}:{self.port}")
            except socket.timeout:
                msg = f"Connection timed out reaching {self.host}:{self.port}. Check firewall, port forwarding, or network."
                self.log("error", msg)
                return {"status": "error", "message": msg}
            except OSError as e:
                msg = f"Network pre-check failed to {self.host}:{self.port}: {e}"
                self.log("error", msg)
                return {"status": "error", "message": msg}
            finally:
                if test_socket:
                    try:
                        test_socket.close()
                    except Exception:
                        pass

            try:
                if conn_type == "TCP":
                    self.client = ModbusTcpClient(host=self.host, port=self.port, timeout=10)
                elif conn_type == "Telnet (RTU over TCP)":
                    socket_url = f"socket://{self.host}:{self.port}"
                    self.client = ModbusSerialClient(port=socket_url, framer="rtu", timeout=15)
                else:
                    return {"status": "error", "message": f"Unsupported connection type: {conn_type}"}

                if self.client.connect():
                    self.is_connected = True
                    self.log("success", f"Connection established successfully ({conn_type}) to {self.host}:{self.port}")
                    return {"status": "success", "message": f"Connected ({conn_type})"}
                else:
                    self.is_connected = False
                    if self.client:
                        try:
                            self.client.close()
                        except Exception:
                            pass
                    self.client = None
                    msg = f"Modbus handshake failed to {self.host}:{self.port}. Verify meter device is running."
                    self.log("error", msg)
                    return {"status": "error", "message": msg}

            except Exception as e:
                self.is_connected = False
                self.client = None
                msg = f"Connection exception: {e}"
                self.log("error", msg)
                return {"status": "error", "message": msg}

    def _disconnect_internal(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None
        self.is_connected = False
        self.calib_mode_active = False
        self.section1_write_enabled = False
        self.mode_status = "Mode: OFF"

    def disconnect(self) -> Dict[str, Any]:
        with self.lock:
            if not self.is_connected:
                return {"status": "info", "message": "Already disconnected."}
            self._disconnect_internal()
            self.log("info", "Disconnected from Modbus meter.")
            return {"status": "success", "message": "Disconnected"}

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "is_connected": self.is_connected,
                "is_simulation": self.is_simulation,
                "conn_type": self.conn_type,
                "host": self.host,
                "port": self.port,
                "slave_id": self.slave_id,
                "section1_write_enabled": self.section1_write_enabled,
                "calib_mode_active": self.calib_mode_active,
                "mode_status": self.mode_status,
                "last_readings": self.last_readings,
            }

    def _safe_modbus_call(self, func, *args, **kwargs):
        """Invoke Modbus function handling both pymodbus 2.x and 3.x slave/unit parameter differences."""
        try:
            return func(*args, **kwargs)
        except TypeError:
            # Fallback if pymodbus 2.x requires 'unit' instead of 'slave' or vice versa
            if "slave" in kwargs:
                kwargs["unit"] = kwargs.pop("slave")
                return func(*args, **kwargs)
            elif "unit" in kwargs:
                kwargs["slave"] = kwargs.pop("unit")
                return func(*args, **kwargs)
            raise

    def write_secret_code(self, code_input: str) -> Dict[str, Any]:
        """Send Secret Code to Register 30 to enable Section 1 Write Mode or Calibration Mode."""
        if not self.is_connected:
            return {"status": "error", "message": "Cannot send secret code: Not connected."}

        try:
            code_str = code_input.strip()
            if code_str.lower().startswith("0x"):
                code = int(code_str, 16)
            else:
                code = int(code_str) if code_str else 0
        except ValueError:
            msg = "Invalid secret code format. Enter integer or hex (e.g., 0xDCBA)."
            self.log("error", msg)
            return {"status": "error", "message": msg}

        if self.is_simulation:
            with self.lock:
                if code == SECRET_CODE_VALUE_SECTION1:
                    self.section1_write_enabled = True
                    self.calib_mode_active = False
                    self.mode_status = "Mode: SEC1 WRITE"
                    self.log("success", f"[SIMULATION] Code {hex(code)} accepted: SECTION 1 WRITE mode ENABLED.")
                    return {"status": "success", "mode": "SEC1_WRITE", "message": "Section 1 Write Mode ENABLED."}
                elif code == SECRET_CODE_VALUE:
                    self.section1_write_enabled = False
                    self.calib_mode_active = True
                    self.mode_status = "Mode: CALIBRATION"
                    self.log("success", f"[SIMULATION] Code {hex(code)} accepted: CALIBRATION mode ENABLED.")
                    return {"status": "success", "mode": "CALIBRATION", "message": "Calibration Mode ENABLED."}
                else:
                    self.section1_write_enabled = False
                    self.calib_mode_active = False
                    self.mode_status = "Mode: OFF"
                    self.log("info", f"[SIMULATION] Code {hex(code)}: All special write modes DISABLED.")
                    return {"status": "success", "mode": "OFF", "message": "All special write modes DISABLED."}

        try:
            self.log("info", f"Writing secret code {hex(code)} to Register {REG_SECRET_CODE} (Slave: {self.slave_id})...")
            rq = self._safe_modbus_call(self.client.write_register, address=REG_SECRET_CODE, value=code, slave=self.slave_id)
            if rq is None or (hasattr(rq, 'isError') and rq.isError()):
                self.log("error", f"Failed to write secret code to Slave {self.slave_id}.")
                return {"status": "error", "message": "Modbus write failed for secret code."}

            with self.lock:
                if code == SECRET_CODE_VALUE_SECTION1:
                    self.section1_write_enabled = True
                    self.calib_mode_active = False
                    self.mode_status = "Mode: SEC1 WRITE"
                    self.log("success", f"Code {hex(code)} accepted. SECTION 1 WRITE mode ENABLED.")
                    return {"status": "success", "mode": "SEC1_WRITE", "message": "Section 1 Write Mode ENABLED."}
                elif code == SECRET_CODE_VALUE:
                    self.section1_write_enabled = False
                    self.calib_mode_active = True
                    self.mode_status = "Mode: CALIBRATION"
                    self.log("success", f"Code {hex(code)} accepted. CALIBRATION mode ENABLED.")
                    return {"status": "success", "mode": "CALIBRATION", "message": "Calibration Mode ENABLED."}
                else:
                    self.section1_write_enabled = False
                    self.calib_mode_active = False
                    self.mode_status = "Mode: OFF"
                    self.log("info", f"Code {hex(code)} processed: All special write modes DISABLED.")
                    return {"status": "success", "mode": "OFF", "message": "All write modes DISABLED."}

        except Exception as e:
            msg = f"Error writing secret code: {e}"
            self.log("error", msg)
            return {"status": "error", "message": msg}

    def read_section1(self) -> Dict[str, Any]:
        """Read Section 1 Holding Registers matching 4.py blocks."""
        if not self.is_connected:
            return {"status": "error", "message": "Not connected to meter."}

        if self.is_simulation:
            # Add subtle realistic jitter in simulation mode
            jitter = (random.random() - 0.5) * 0.05
            self.sim_data["flowRate"] = max(0.0, round(self.sim_data["flowRate"] + jitter, 3))
            self.sim_data["totalVolume64"] = round(self.sim_data["totalVolume64"] + (self.sim_data["flowRate"] / 3600.0), 6)
            self.sim_data["fwdVolume"] = round(self.sim_data["fwdVolume"] + (self.sim_data["flowRate"] / 3600.0), 3)
            self.sim_data["pumpMins"] = round(self.sim_data["pumpMins"] + 0.05, 1)

            results = {
                "flowRate": f"{self.sim_data['flowRate']:.3f}",
                "totalVolume64": f"{self.sim_data['totalVolume64']:.6f}",
                "tempVal": f"{self.sim_data['tempVal']:.3f}",
                "fwdVolume": f"{self.sim_data['fwdVolume']:.3f}",
                "revVolume": f"{self.sim_data['revVolume']:.3f}",
                "pumpMins": f"{self.sim_data['pumpMins']:.1f}",
                "signal": f"{self.sim_data['signal']:.1f}",
                "tamper": str(self.sim_data["tamper"]),
                "read_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with self.lock:
                self.last_readings = results
            self.log("info", f"[SIMULATION] Read Section 1 -> Flow: {results['flowRate']} m³/h, Total: {results['totalVolume64']} m³, Signal: {results['signal']} dBm")
            return {"status": "success", "data": results}

        try:
            self.log("info", f"Reading Section 1 from Slave {self.slave_id}...")
            readings = {}

            # Block 1: Flow Rate (Address 0, count 2 -> float32)
            rr1 = self._safe_modbus_call(self.client.read_holding_registers, address=REG_FLOW_RATE_HIGH, count=2, slave=self.slave_id)
            if rr1 and hasattr(rr1, 'registers') and len(rr1.registers) >= 2:
                dec = BinaryPayloadDecoder.fromRegisters(rr1.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                readings["flowRate"] = f"{dec.decode_32bit_float():.3f}"
            else:
                readings["flowRate"] = "Read Error"

            # Block 2: Temp Val (Address 2, count 2 -> float32)
            rr2 = self._safe_modbus_call(self.client.read_holding_registers, address=REG_TEMP_VAL_HIGH, count=2, slave=self.slave_id)
            if rr2 and hasattr(rr2, 'registers') and len(rr2.registers) >= 2:
                dec = BinaryPayloadDecoder.fromRegisters(rr2.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                readings["tempVal"] = f"{dec.decode_32bit_float():.3f}"
            else:
                readings["tempVal"] = "Read Error"

            # Block 3: Fwd Volume, Rev Volume, Pump Mins, Signal Strength (Address 4 to 11, count 8 -> four float32)
            count3 = (REG_SIGNAL_STRENGTH_LOW - REG_FWD_VOLUME_HIGH) + 1  # 8 registers
            rr3 = self._safe_modbus_call(self.client.read_holding_registers, address=REG_FWD_VOLUME_HIGH, count=count3, slave=self.slave_id)
            if rr3 and hasattr(rr3, 'registers') and len(rr3.registers) >= count3:
                dec = BinaryPayloadDecoder.fromRegisters(rr3.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                readings["fwdVolume"] = f"{dec.decode_32bit_float():.3f}"
                readings["revVolume"] = f"{dec.decode_32bit_float():.3f}"
                readings["pumpMins"] = f"{dec.decode_32bit_float():.1f}"
                readings["signal"] = f"{dec.decode_32bit_float():.1f}"
            else:
                readings["fwdVolume"] = "Read Error"
                readings["revVolume"] = "Read Error"
                readings["pumpMins"] = "Read Error"
                readings["signal"] = "Read Error"

            # Block 4: Total Volume 64-bit (Address 12, count 4 -> float64)
            rr4 = self._safe_modbus_call(self.client.read_holding_registers, address=REG_TOTAL_VOLUME_64_ADDR_START, count=4, slave=self.slave_id)
            if rr4 and hasattr(rr4, 'registers') and len(rr4.registers) >= 4:
                dec = BinaryPayloadDecoder.fromRegisters(rr4.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                readings["totalVolume64"] = f"{dec.decode_64bit_float():.6f}"
            else:
                readings["totalVolume64"] = "Read Error"

            # Block 5: Tamper Status (Address 44, count 1 -> uint16)
            rr5 = self._safe_modbus_call(self.client.read_holding_registers, address=REG_TAMPER_STATUS, count=1, slave=self.slave_id)
            if rr5 and hasattr(rr5, 'registers') and len(rr5.registers) >= 1:
                dec = BinaryPayloadDecoder.fromRegisters(rr5.registers, byteorder=Endian.BIG, wordorder=Endian.BIG)
                readings["tamper"] = str(dec.decode_16bit_uint())
            else:
                readings["tamper"] = "Read Error"

            readings["read_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with self.lock:
                self.last_readings = readings

            self.log("success", f"Section 1 read successful. Flow: {readings.get('flowRate')} m³/h, Total: {readings.get('totalVolume64')} m³")
            return {"status": "success", "data": readings}

        except Exception as e:
            msg = f"Exception reading Section 1 from Slave {self.slave_id}: {e}"
            self.log("error", msg)
            return {"status": "error", "message": msg}

    def write_section1(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Write Section 1 values matching 4.py write_section1."""
        if not self.is_connected:
            return {"status": "error", "message": "Not connected to meter."}

        if not self.section1_write_enabled:
            msg = "Permission Denied: Section 1 Write Mode not active. Send secret code 0xDCBA first."
            self.log("warning", msg)
            return {"status": "error", "message": msg}

        if self.is_simulation:
            with self.lock:
                for key in ["flowRate", "tempVal", "fwdVolume", "revVolume", "pumpMins", "signal", "totalVolume64"]:
                    if key in values and values[key] != "":
                        try:
                            self.sim_data[key] = float(values[key])
                        except ValueError:
                            pass
            self.log("success", f"[SIMULATION] Section 1 written successfully with updated values.")
            return {"status": "success", "message": "Section 1 written successfully (Simulation Mode)."}

        try:
            self.log("info", f"Writing Section 1 values to Slave {self.slave_id}...")

            # Block 1: Flow Rate (Addr 0, float32)
            builder1 = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
            builder1.add_32bit_float(float(values["flowRate"]))
            p1 = builder1.to_registers()
            rq1 = self._safe_modbus_call(self.client.write_registers, address=REG_FLOW_RATE_HIGH, values=p1, slave=self.slave_id)
            if rq1 is None or (hasattr(rq1, 'isError') and rq1.isError()):
                msg = f"Failed writing Flow Rate to Reg {REG_FLOW_RATE_HIGH}"
                self.log("error", msg)
                return {"status": "error", "message": msg}

            # Block 2: Temp Val (Addr 2, float32)
            builder2 = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
            builder2.add_32bit_float(float(values["tempVal"]))
            p2 = builder2.to_registers()
            rq2 = self._safe_modbus_call(self.client.write_registers, address=REG_TEMP_VAL_HIGH, values=p2, slave=self.slave_id)
            if rq2 is None or (hasattr(rq2, 'isError') and rq2.isError()):
                msg = f"Failed writing Temp Val to Reg {REG_TEMP_VAL_HIGH}"
                self.log("error", msg)
                return {"status": "error", "message": msg}

            # Block 3: Fwd Volume, Rev Volume, Pump Mins, Signal Strength (Addr 4, 8 regs)
            builder3 = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
            builder3.add_32bit_float(float(values["fwdVolume"]))
            builder3.add_32bit_float(float(values["revVolume"]))
            builder3.add_32bit_float(float(values["pumpMins"]))
            builder3.add_32bit_float(float(values["signal"]))
            p3 = builder3.to_registers()
            rq3 = self._safe_modbus_call(self.client.write_registers, address=REG_FWD_VOLUME_HIGH, values=p3, slave=self.slave_id)
            if rq3 is None or (hasattr(rq3, 'isError') and rq3.isError()):
                msg = f"Failed writing Volume & Signal block to Reg {REG_FWD_VOLUME_HIGH}"
                self.log("error", msg)
                return {"status": "error", "message": msg}

            # Block 4: Total Volume 64-bit (Addr 12, float64)
            builder4 = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
            builder4.add_64bit_float(float(values["totalVolume64"]))
            p4 = builder4.to_registers()
            rq4 = self._safe_modbus_call(self.client.write_registers, address=REG_TOTAL_VOLUME_64_ADDR_START, values=p4, slave=self.slave_id)
            if rq4 is None or (hasattr(rq4, 'isError') and rq4.isError()):
                msg = f"Failed writing Total Volume 64-bit to Reg {REG_TOTAL_VOLUME_64_ADDR_START}"
                self.log("error", msg)
                return {"status": "error", "message": msg}

            self.log("success", f"Section 1 write completed successfully for Slave {self.slave_id}.")
            return {"status": "success", "message": f"Section 1 written successfully to Slave {self.slave_id}."}

        except ValueError as ve:
            msg = f"Invalid number format in Section 1 write fields: {ve}"
            self.log("error", msg)
            return {"status": "error", "message": msg}
        except Exception as e:
            msg = f"Exception writing Section 1: {e}"
            self.log("error", msg)
            return {"status": "error", "message": msg}

# Global singleton
modbus_service = ModbusService()
