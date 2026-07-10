import { useEffect, useState } from "react";
import { ChartPanel } from "./features/chart/ChartPanel";
import { getAppConfig, getHealth, type AppConfig } from "./shared/api/client";

export default function App() {
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");

  useEffect(() => {
    getHealth()
      .then(() => setBackendUp(true))
      .catch(() => setBackendUp(false));
    getAppConfig().then(setConfig).catch(() => {});
  }, []);

  return (
    <div className="layout">
      <header className="topbar">
        <h1>AI Trading Bot</h1>
        {config && (
          <span className={`mode mode-${config.mode}`}>{config.mode.toUpperCase()}</span>
        )}
        <nav className="symbols">
          {(config?.symbols ?? ["XAUUSD", "XAGUSD", "BTCUSD"]).map((s) => (
            <button key={s} className={s === symbol ? "active" : ""} onClick={() => setSymbol(s)}>
              {s}
            </button>
          ))}
        </nav>
        <span className="status">
          backend:{" "}
          {backendUp === null ? (
            "…"
          ) : backendUp ? (
            <em className="ok">connected</em>
          ) : (
            <em className="err">offline</em>
          )}
        </span>
      </header>

      <main>
        <ChartPanel symbol={symbol} />
        <aside className="sidebar">
          <section className="panel">Account · MT5 login (Phase 1)</section>
          <section className="panel">Bot control (Phase 4)</section>
          <section className="panel">Journal (Phase 3)</section>
          <section className="panel">AI reports (Phase 6–7)</section>
          <section className="panel">News (Phase 8)</section>
        </aside>
      </main>
    </div>
  );
}
