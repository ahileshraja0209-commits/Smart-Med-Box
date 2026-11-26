import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ESP_INO_PATH = os.path.join(BASE_DIR, "esp.ino")
SECRETS_PATH = os.path.join(BASE_DIR, "medbox_secrets.env")
PORT = int(os.environ.get("MEDBOX_PORT", "5500"))


def read_local_gemini_key() -> str:
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(SECRETS_PATH):
        with open(SECRETS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return ""


def escape_cpp_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read_current_wifi():
    if not os.path.exists(ESP_INO_PATH):
        return {"ssid": "", "password": ""}
    with open(ESP_INO_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    ssid_match = re.search(r'#define\s+WIFI_SSID\s+"([^"\\]*(?:\\.[^"\\]*)*)"', content)
    pass_match = re.search(r'#define\s+WIFI_PASSWORD\s+"([^"\\]*(?:\\.[^"\\]*)*)"', content)
    return {
        "ssid": ssid_match.group(1) if ssid_match else "",
        "password": pass_match.group(1) if pass_match else "",
    }


def write_wifi_to_esp_ino(ssid: str, password: str):
    if not os.path.exists(ESP_INO_PATH):
        raise FileNotFoundError(f"esp.ino not found at {ESP_INO_PATH}")

    with open(ESP_INO_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    safe_ssid = escape_cpp_string(ssid)
    safe_pass = escape_cpp_string(password)

    updated, ssid_count = re.subn(
        r'(#define\s+WIFI_SSID\s+)"([^"\\]*(?:\\.[^"\\]*)*)"',
        lambda m: f'{m.group(1)}"{safe_ssid}"',
        content,
    )
    updated, pass_count = re.subn(
        r'(#define\s+WIFI_PASSWORD\s+)"([^"\\]*(?:\\.[^"\\]*)*)"',
        lambda m: f'{m.group(1)}"{safe_pass}"',
        updated,
    )

    if ssid_count == 0 and pass_count == 0:
        raise ValueError("Could not find #define WIFI_SSID or #define WIFI_PASSWORD in esp.ino")

    with open(ESP_INO_PATH, "w", encoding="utf-8") as f:
        f.write(updated)

    return {"ok": True, "file": "esp.ino", "ssidUpdated": ssid_count > 0, "passwordUpdated": pass_count > 0}


class MedBoxHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status_code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/get-wifi":
            try:
                self._send_json(200, read_current_wifi())
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        if self.path == "/api/gemini-key":
            self._send_json(200, {"apiKey": read_local_gemini_key()})
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/save-wifi":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(raw.decode("utf-8"))
                ssid = str(data.get("ssid", "")).strip()
                password = str(data.get("password", ""))
                if not ssid:
                    self._send_json(400, {"ok": False, "error": "Wi-Fi SSID is required."})
                    return
                result = write_wifi_to_esp_ino(ssid, password)
                self._send_json(200, result)
            except Exception as exc:
                self._send_json(500, {"ok": False, "error": str(exc)})
            return
        self._send_json(404, {"ok": False, "error": "Not found"})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), MedBoxHandler)
    print(f"Smart Medicine Box server running at http://localhost:{PORT}/exp.html")
    server.serve_forever()
