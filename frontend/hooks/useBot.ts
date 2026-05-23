"use client";

import { useEffect, useRef, useState } from "react";

const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

export interface Position {
  symbol: string;
  shares: number;
  entry_price: number;
  current_price: number | null;
  stop: number | null;
  pnl: number | null;
}

export interface Trade {
  id: number;
  symbol: string;
  side: string;
  shares: number;
  entry_price: number | null;
  exit_price: number | null;
  pnl: number | null;
  timestamp: string;
}

export type BotStatus = "running" | "stopped" | "error";

export function useBot() {
  const [status, setStatus] = useState<BotStatus>("stopped");
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // ── initial fetch ──────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API}/bot/status`)
      .then((r) => r.json())
      .then((d) => setStatus(d.status))
      .catch(() => {});

    fetch(`${API}/positions/`)
      .then((r) => r.json())
      .then(setPositions)
      .catch(() => {});

    fetch(`${API}/trades/today`)
      .then((r) => r.json())
      .then(setTrades)
      .catch(() => {});
  }, []);

  // ── WebSocket ──────────────────────────────────────────────────
  useEffect(() => {
    function connect() {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // auto-reconnect
      };

      ws.onmessage = (e) => {
        const { event, data } = JSON.parse(e.data);

        if (event === "bot_status") {
          setStatus(data.status);
        }

        if (event === "position_update") {
          setPositions((prev) => {
            const idx = prev.findIndex((p) => p.symbol === data.symbol);
            if (idx === -1) return [...prev, data];
            const next = [...prev];
            next[idx] = data;
            return next;
          });
        }

        if (event === "trade_fill") {
          const trade: Trade = {
            id: Date.now(),
            symbol: data.symbol,
            side: data.side,
            shares: data.shares,
            entry_price: data.side === "BUY" ? data.price : null,
            exit_price: data.side === "SELL" ? data.price : null,
            pnl: data.pnl ?? null,
            timestamp: data.timestamp,
          };
          setTrades((prev) => [...prev, trade]);

          // remove closed position from table
          if (data.side === "SELL") {
            setPositions((prev) => prev.filter((p) => p.symbol !== data.symbol));
          }
        }

        if (event === "stop_update") {
          setPositions((prev) =>
            prev.map((p) =>
              p.symbol === data.symbol ? { ...p, stop: data.new_stop } : p
            )
          );
        }
      };
    }

    connect();
    return () => wsRef.current?.close();
  }, []);

  // ── actions ────────────────────────────────────────────────────
  async function startBot() {
    await fetch(`${API}/bot/start`, { method: "POST" });
  }

  async function stopBot() {
    await fetch(`${API}/bot/stop`, { method: "POST" });
  }

  // ── derived ────────────────────────────────────────────────────
  const totalPnl = positions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);

  return { status, positions, trades, connected, totalPnl, startBot, stopBot };
}
