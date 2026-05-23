import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";

const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "IBKR Bot Dashboard",
  description: "Intraday trading bot monitor",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={mono.variable}>
      <body className="min-h-screen bg-[#0f1117] antialiased">{children}</body>
    </html>
  );
}
