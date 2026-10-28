import socket
import threading
import time

import requests
import uvicorn

from app.main import app

_HOST = "127.0.0.1"
_PORT = 8199


def _wait_for_port(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex((_HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def test_health_returns_ok() -> None:
    config = uvicorn.Config(app, host=_HOST, port=_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        assert _wait_for_port(_PORT), "uvicorn no arranco a tiempo"
        response = requests.get(f"http://{_HOST}:{_PORT}/health", timeout=5)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    finally:
        server.should_exit = True
        thread.join(timeout=5)
