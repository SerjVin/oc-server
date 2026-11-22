#!/usr/bin/env python3
"""Локальный клиент-серверное приложение для учёта событий.

Сервер отдаёт веб-клиент и принимает два вида запросов:
  POST /api/events — сохранить событие (номер радиокнопки и время);
  GET  /api/events — получить список сохранённых событий.

Записи хранятся в текстовом файле, по одной JSON-записи на строку.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DEFAULT_DATA_FILE = ROOT / "data" / "events.txt"

ALLOWED_EVENTS = frozenset({1, 2, 3})
MAX_BODY_SIZE = 16 * 1024

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class EventStore:
    """Хранилище событий в текстовом файле (JSON Lines)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = Lock()
        self._next_id = 1 + max(
            (record.get("id", 0) for record in self._read_records()),
            default=0,
        )

    def _read_records(self) -> list[dict]:
        """Читает файл, пропуская повреждённые строки."""
        records = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
        return records

    def add(self, event: int, time: str) -> dict:
        with self._lock:
            record = {"id": self._next_id, "event": event, "time": time}
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._next_id += 1
            return record

    def all(self) -> list[dict]:
        with self._lock:
            return self._read_records()


class EventHandler(BaseHTTPRequestHandler):
    server_version = "EventServer/1.0"
    store: EventStore

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str, content_type: str) -> None:
        try:
            body = (STATIC_DIR / filename).read_bytes()
        except OSError:
            self.send_error(404, "Файл не найден")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _bad_request(self, message: str) -> None:
        self._send_json(400, {"error": message})

    def do_OPTIONS(self) -> None:
        self._send_json(204, {})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/events":
            self._send_json(200, {"events": self.store.all()})
            return
        static = STATIC_FILES.get(path)
        if static is not None:
            self._send_static(*static)
            return
        self.send_error(404, "Страница не найдена")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/events":
            self.send_error(404, "Маршрут не найден")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._bad_request("Некорректный Content-Length")
            return
        if length <= 0 or length > MAX_BODY_SIZE:
            self._bad_request("Некорректный размер запроса")
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._bad_request("Ожидался корректный JSON")
            return
        if not isinstance(payload, dict):
            self._bad_request("Ожидался объект JSON")
            return

        event = payload.get("event")
        if isinstance(event, bool) or not isinstance(event, int) or event not in ALLOWED_EVENTS:
            self._bad_request("event должен быть числом 1, 2 или 3")
            return

        time_value = payload.get("time")
        if not isinstance(time_value, str) or not time_value.strip():
            self._bad_request("time должен быть строкой с временем")
            return
        try:
            parsed_time = datetime.fromisoformat(time_value.replace("Z", "+00:00"))
        except ValueError:
            self._bad_request("time должен быть в формате ISO 8601")
            return
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        normalized_time = parsed_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        record = self.store.add(event, normalized_time)
        self._send_json(201, {"ok": True, "event": record})


def local_ip() -> str | None:
    """Возвращает локальный IP в сети (без фактической отправки данных)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))  # адрес из документации, пакеты не отправляются
            return sock.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Сервер учёта событий")
    parser.add_argument("--host", default="0.0.0.0", help="адрес прослушивания (по умолчанию 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="порт (по умолчанию 8000)")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_FILE, help="путь к файлу событий")
    args = parser.parse_args()

    store = EventStore(args.data)

    class Handler(EventHandler):
        pass

    Handler.store = store
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    print(f"Сервер запущен: http://localhost:{args.port}", flush=True)
    ip = local_ip()
    if ip:
        print(f"Для Android/другого устройства в той же сети: http://{ip}:{args.port}", flush=True)
    print(f"Файл событий: {store.path}", flush=True)
    print("Для остановки нажмите Ctrl+C", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
