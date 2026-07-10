import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Trading Bot",
  description: "MT5-connected, AI-assisted trading bot — XAUUSD / XAGUSD / BTCUSD",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg font-sans text-ink antialiased">{children}</body>
    </html>
  );
}
