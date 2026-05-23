"use client";

import { useEffect, useState } from "react";
import { useBot } from "@/hooks/useBot";

// ── helpers ────────────────────────────────────────────────────────

function fmt(n: number | null, prefix = "") {
  if (n === null || n === undefined) return "—";
  return `${prefix}${n.toFixed(2)}`;
}

function pnlClass(n: number | null) {
  if (n === null) return "text-zinc-500";
  return n >= 0 ? "text-emerald-400" : "text-red-400";
}

function useUptime(running: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) { setSeconds(0); return; }
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [running]);
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

// ── page ───────────────────────────────────────────────────────────

export default function Dashboard() {
  const { status, positions, trades, connected, totalPnl, startBot, stopBot } = useBot();
  const uptime = useUptime(status === "running");
  const todayPnl = trades.reduce((s, t) => s + (t.pnl ?? 0), 0);

  return (
    <div className="flex min-h-screen bg-[#0c0e14] text-zinc-100">

      {/* ── sidebar ── */}
      <aside className="w-56 shrink-0 border-r border-zinc-800/60 flex flex-col">
        {/* logo */}
        <div className="px-6 py-5 border-b border-zinc-800/60">
          <p className="text-sm font-bold tracking-widest text-zinc-100 uppercase">IBKR Bot</p>
          <p className="text-[11px] text-zinc-600 mt-0.5 tracking-wide">Intraday Dashboard</p>
        </div>

        {/* nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <NavItem icon="▣" label="Dashboard" active />
          <NavItem icon="↗" label="Positions" />
          <NavItem icon="≡" label="Trade Log" />
        </nav>

        {/* connection status */}
        <div className="px-5 py-4 border-t border-zinc-800/60">
          <div className="flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-emerald-400 shadow-[0_0_6px_#34d399]" : "bg-zinc-600"}`} />
            <span className="text-[11px] text-zinc-500 tracking-wide">
              {connected ? "CONNECTED" : "DISCONNECTED"}
            </span>
          </div>
        </div>
      </aside>

      {/* ── main ── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* top bar */}
        <header className="border-b border-zinc-800/60 px-8 py-4 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-zinc-100 tracking-wide">Overview</h1>
            <StatusBadge status={status} />
          </div>

          <div className="flex items-center gap-3">
            {status === "running" && (
              <span className="text-xs font-mono text-zinc-500 tabular-nums">
                {uptime}
              </span>
            )}
            <button
              onClick={startBot}
              disabled={status === "running"}
              className="text-xs font-semibold px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-25 disabled:cursor-not-allowed transition-all"
            >
              Start Bot
            </button>
            <button
              onClick={stopBot}
              disabled={status !== "running"}
              className="text-xs font-semibold px-4 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 hover:border-red-500/50 disabled:opacity-25 disabled:cursor-not-allowed transition-all"
            >
              Stop Bot
            </button>
          </div>
        </header>

        {/* content */}
        <main className="flex-1 px-8 py-7 space-y-8 overflow-auto">

          {/* stat cards */}
          <div className="grid grid-cols-4 gap-4">
            <StatCard
              label="Bot Status"
              value={status.charAt(0).toUpperCase() + status.slice(1)}
              valueClass={status === "running" ? "text-emerald-400" : status === "error" ? "text-red-400" : "text-zinc-400"}
              sub={status === "running" ? uptime : "—"}
            />
            <StatCard
              label="Open Positions"
              value={String(positions.length)}
              sub={positions.length === 1 ? "1 symbol active" : `${positions.length} symbols active`}
            />
            <StatCard
              label="Unrealised P&L"
              value={`$${totalPnl.toFixed(2)}`}
              valueClass={pnlClass(totalPnl)}
              sub="across open positions"
            />
            <StatCard
              label="Realised P&L Today"
              value={`$${todayPnl.toFixed(2)}`}
              valueClass={pnlClass(todayPnl)}
              sub={`${trades.filter(t => t.side === "SELL").length} closed trades`}
            />
          </div>

          {/* positions */}
          <Section title="Open Positions" count={positions.length}>
            {positions.length === 0 ? (
              <Empty text="No open positions — bot is watching for setups" />
            ) : (
              <Table
                headers={["Symbol", "Shares", "Entry Price", "Current Price", "Stop", "P&L"]}
                rows={positions.map((p) => [
                  <Ticker key="t" symbol={p.symbol} />,
                  <Mono key="s">{p.shares}</Mono>,
                  <Mono key="e">{fmt(p.entry_price, "$")}</Mono>,
                  <Mono key="c">{fmt(p.current_price, "$")}</Mono>,
                  <Mono key="st" className="text-amber-400">{fmt(p.stop, "$")}</Mono>,
                  <Mono key="p" className={pnlClass(p.pnl)}>{fmt(p.pnl, "$")}</Mono>,
                ])}
              />
            )}
          </Section>

          {/* trade log */}
          <Section title="Today's Trade Log" count={trades.length}>
            {trades.length === 0 ? (
              <Empty text="No trades executed today" />
            ) : (
              <Table
                headers={["Time", "Symbol", "Side", "Shares", "Entry", "Exit", "P&L"]}
                rows={[...trades].reverse().map((t) => [
                  <Mono key="ts" className="text-zinc-500">{new Date(t.timestamp).toLocaleTimeString()}</Mono>,
                  <Ticker key="sym" symbol={t.symbol} />,
                  <span key="side" className={`text-xs font-bold tracking-widest ${t.side === "BUY" ? "text-emerald-400" : "text-red-400"}`}>{t.side}</span>,
                  <Mono key="sh">{t.shares}</Mono>,
                  <Mono key="en">{fmt(t.entry_price, "$")}</Mono>,
                  <Mono key="ex">{fmt(t.exit_price, "$")}</Mono>,
                  <Mono key="pnl" className={pnlClass(t.pnl)}>{fmt(t.pnl, "$")}</Mono>,
                ])}
              />
            )}
          </Section>

        </main>
      </div>
    </div>
  );
}

// ── components ─────────────────────────────────────────────────────

function NavItem({ icon, label, active = false }: { icon: string; label: string; active?: boolean }) {
  return (
    <div className={`flex items-center gap-2.5 px-3 py-2 rounded-md cursor-pointer text-sm transition-colors
      ${active ? "bg-zinc-800 text-zinc-100" : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50"}`}>
      <span className="text-xs opacity-60">{icon}</span>
      <span className="tracking-wide">{label}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    running: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    stopped: "bg-zinc-800 text-zinc-500 border-zinc-700",
    error:   "bg-red-500/10 text-red-400 border-red-500/20",
  };
  return (
    <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full border tracking-widest uppercase ${styles[status]}`}>
      {status}
    </span>
  );
}

function StatCard({ label, value, valueClass = "text-zinc-100", sub }: {
  label: string; value: string; valueClass?: string; sub?: string;
}) {
  return (
    <div className="bg-zinc-900/60 border border-zinc-800/80 rounded-xl px-5 py-4 hover:border-zinc-700 transition-colors">
      <p className="text-[11px] text-zinc-500 uppercase tracking-widest mb-2">{label}</p>
      <p className={`text-2xl font-bold font-mono tabular-nums ${valueClass}`}>{value}</p>
      {sub && <p className="text-[11px] text-zinc-600 mt-1.5">{sub}</p>}
    </div>
  );
}

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section>
      <div className="flex items-center gap-2.5 mb-3">
        <h2 className="text-sm font-semibold text-zinc-300">{title}</h2>
        <span className="text-[11px] bg-zinc-800 text-zinc-500 px-2 py-0.5 rounded-full tabular-nums">{count}</span>
      </div>
      {children}
    </section>
  );
}

function Table({ headers, rows }: { headers: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-zinc-900/80 border-b border-zinc-800">
            {headers.map((h) => (
              <th key={h} className="text-left text-[11px] text-zinc-500 uppercase tracking-widest px-5 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-800/50">
          {rows.map((row, i) => (
            <tr key={i} className={`transition-colors hover:bg-zinc-800/30 ${i % 2 === 0 ? "bg-transparent" : "bg-zinc-900/20"}`}>
              {row.map((cell, j) => (
                <td key={j} className="px-5 py-3.5">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Ticker({ symbol }: { symbol: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/70" />
      <span className="font-bold text-zinc-100 tracking-wide">{symbol}</span>
    </span>
  );
}

function Mono({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`font-mono tabular-nums text-zinc-300 ${className}`}>{children}</span>;
}

function Empty({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-zinc-800/80 border-dashed bg-zinc-900/20 px-6 py-10 text-center">
      <p className="text-sm text-zinc-600">{text}</p>
    </div>
  );
}
