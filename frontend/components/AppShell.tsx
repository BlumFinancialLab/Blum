"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { BarChart3, Brain, Cpu, Database, Gauge, LineChart, Network, Radar, Search, ShieldAlert, type LucideIcon } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import { SystemStatus } from "@/lib/types";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  aliases?: string[];
};

const nav: NavItem[] = [
  { href: "/", label: "Dashboard", icon: Gauge, aliases: ["/dashboard"] },
  { href: "/market-brain", label: "Market Brain", icon: Cpu },
  { href: "/stock-radar", label: "Radar", icon: Radar, aliases: ["/etf-radar", "/ipo-radar", "/assets"] },
  { href: "/chart-analyst", label: "Chart Analyst", icon: LineChart },
  { href: "/themes", label: "Themes", icon: Network },
  { href: "/signal-lab", label: "Signal Lab", icon: Search },
  { href: "/methodology", label: "Methodology", icon: Brain }
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    api.systemStatus().then(setSystemStatus).catch(() => setSystemStatus(null));
  }, []);

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
            const active = pathname === item.href || item.aliases?.some((alias) => pathname.startsWith(alias)) || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link href={item.href} key={item.href} className={clsx("nav-item", active && "active")}>
                <Icon size={17} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="system-card">
          <div><Database size={15} /> Build v{systemStatus?.app_version ?? "loading"}</div>
          <div><BarChart3 size={15} /> {systemStatus?.database_counts?.news_articles ?? 0} news | {systemStatus?.database_counts?.signals ?? 0} signals</div>
          <div><Cpu size={15} /> {systemStatus?.runtime_flags.financial_brain_model_enabled ? "Finance LLM active" : "Evidence brain fallback"}</div>
          <div><ShieldAlert size={15} /> Research only</div>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
