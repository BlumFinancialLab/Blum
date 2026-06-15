"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, Brain, Database, FlaskConical, Gauge, Home, Network, Radar, Search, ShieldAlert, TrendingUp } from "lucide-react";
import clsx from "clsx";

const nav = [
  { href: "/", label: "Case Study", icon: Home },
  { href: "/dashboard", label: "Intelligence Dashboard", icon: Gauge },
  { href: "/assets/NVDA", label: "Asset Detail", icon: Activity },
  { href: "/stock-radar", label: "Stock Radar", icon: TrendingUp },
  { href: "/etf-radar", label: "ETF Radar", icon: Radar },
  { href: "/themes", label: "Theme Explorer", icon: Network },
  { href: "/signal-lab", label: "Signal Lab", icon: Search },
  { href: "/backtest", label: "Backtest", icon: FlaskConical },
  { href: "/methodology", label: "Methodology", icon: Brain }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div>
            <strong>Blum</strong>
            <span>AI Financial Intelligence</span>
          </div>
        </div>
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link href={item.href} key={item.href} className={clsx("nav-item", active && "active")}>
                <Icon size={17} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="system-card">
          <div><Database size={15} /> PostgreSQL</div>
          <div><BarChart3 size={15} /> FastAPI + Next.js</div>
          <div><ShieldAlert size={15} /> Research only</div>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
