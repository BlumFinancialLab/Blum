"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Brain, Copy, Cpu, Database, Dumbbell, ShieldAlert, TrendingUp, type LucideIcon } from "lucide-react";
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
  { href: "/", label: "Brain", icon: Brain, aliases: ["/dashboard"] },
  { href: "/training-ground", label: "Training", icon: Dumbbell, aliases: ["/learning"] },
  { href: "/paper-trading", label: "Paper Trading", icon: Copy, aliases: ["/copy-trading"] },
  { href: "/alpha", label: "Alpha", icon: TrendingUp }
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
            <span>Trader Brain</span>
          </div>
        </div>
        <div className="sidebar-market-state">
          <Activity size={15} />
          <div>
            <strong>{systemStatus?.database_counts?.signals ?? 0} signals</strong>
            <span>{systemStatus?.database_counts?.news_articles ?? 0} news articles indexed</span>
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
          <div><Database size={15} /> v{systemStatus?.app_version ?? "loading"} | {systemStatus?.feature_set ?? "loading"}</div>
          <div><Cpu size={15} /> {systemStatus?.runtime_flags.financial_brain_model_enabled ? "Finance LLM active" : "Evidence fallback"}</div>
          <div><Brain size={15} /> {systemStatus?.active_models?.financial_brain_configured ?? "model pending"}</div>
          <div><ShieldAlert size={15} /> Research only</div>
          <Link href="/performance">Developer diagnostics</Link>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
