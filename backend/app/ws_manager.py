import json
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)

    async def broadcast(self, event: str, data: dict):
        message = json.dumps({"event": event, "data": data})
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                self._connections.remove(ws)


ws_manager = WebSocketManager()
