import type { Metadata } from "next";
import { LoginGate } from "@/features/auth/LoginGate";
import { NavigationProvider, NavigationDrawer } from "@/shared/ui/NavigationDrawer";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Trading Bot",
  description: "MT5-connected, AI-assisted trading bot for any broker-tradeable symbol",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-bg font-sans text-ink antialiased">
        <LoginGate>
          <NavigationProvider>
            <NavigationDrawer />
            {children}
          </NavigationProvider>
        </LoginGate>
      </body>
    </html>
  );
}
