import React, { useEffect, useState } from "react";
import ShieldIcon from "./ShieldIcon";
import "./App.css";

export default function App() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/status")
      .then((r) => r.json())
      .then((data) => {
        setStatus(data);
        setLoading(false);
      })
      .catch(() => {
        setStatus({ message: "Backend offline", status: "error" });
        setLoading(false);
      });
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div className="logo">
          <ShieldIcon size={40} />
          <span className="logo-text">Runway Shield</span>
        </div>
      </header>

      <main className="hero">
        <div className="hero-icon">
          <ShieldIcon size={120} />
        </div>

        <h1 className="hero-title">Runway Shield</h1>
        <p className="hero-subtitle">Airport runway monitoring & protection</p>

        <div className={`status-card ${status?.status === "ok" ? "ok" : "err"}`}>
          {loading ? (
            <span className="pulse">Connecting...</span>
          ) : (
            <>
              <span
                className={`dot ${status?.status === "ok" ? "green" : "red"}`}
              />
              <span>{status?.message}</span>
            </>
          )}
        </div>
      </main>

      <footer className="footer">
        <span>&copy; {new Date().getFullYear()} Runway Shield</span>
      </footer>
    </div>
  );
}
