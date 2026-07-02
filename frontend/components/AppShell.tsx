"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, Brain, Clock, Copy, Cpu, Dumbbell, TrendingUp, type LucideIcon } from "lucide-react";
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
  { href: "/brain", label: "Brain", icon: Brain, aliases: ["/dashboard"] },
  { href: "/training-ground", label: "Training Ground", icon: Dumbbell, aliases: ["/learning"] },
  { href: "/paper-trading", label: "Paper Trading", icon: Copy, aliases: ["/copy-trading"] },
  { href: "/alpha", label: "Alpha", icon: TrendingUp }
];

type SidebarStatus = {
  workerStatus: string;
  modelStatus: string;
  lastLearningCycle: string;
  paperForwardStatus: string;
  alphaEvidenceGrade: string;
};

const defaultSidebarStatus: SidebarStatus = {
  workerStatus: "checking",
  modelStatus: "checking",
  lastLearningCycle: "checking",
  paperForwardStatus: "checking",
  alphaEvidenceGrade: "checking",
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [sidebarStatus, setSidebarStatus] = useState<SidebarStatus>(defaultSidebarStatus);

  useEffect(() => {
    let mounted = true;
    Promise.allSettled([
      api.systemStatus(),
      api.learningSummary(),
      api.dashboardSnapshot("paper_forward_snapshot"),
      api.traderAlpha(),
    ]).then(([systemResult, learningResult, paperResult, alphaResult]) => {
      if (!mounted) return;
      const system = systemResult.status === "fulfilled" ? systemResult.value : null;
      const learning = learningResult.status === "fulfilled" ? learningResult.value : null;
      const paper = paperResult.status === "fulfilled" ? paperResult.value : null;
      const alpha = alphaResult.status === "fulfilled" ? alphaResult.value : null;
      setSystemStatus(system);
      setSidebarStatus({
        workerStatus: system?.runtime_flags?.autonomous_engine_enabled ? "workers on" : "workers off",
        modelStatus: system?.runtime_flags?.financial_brain_model_enabled ? "model active" : "snapshot mode",
        lastLearningCycle: compactStatus(learning?.latest_learning_run_at ?? learning?.latest_run_timestamp ?? learning?.latest_learning_run_status ?? learning?.status),
        paperForwardStatus: compactStatus(paper?.payload?.readiness ?? paper?.payload?.status ?? paper?.status),
        alphaEvidenceGrade: compactStatus(alpha?.evidence_grade ?? alpha?.current_alpha_readiness?.evidence_grade ?? alpha?.status),
      });
    }).catch(() => {
      if (mounted) setSidebarStatus(defaultSidebarStatus);
    });
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div>
            <strong>BLUM</strong>
            <span>Trader Brain</span>
          </div>
        </div>
        <div className="sidebar-market-state">
          <Activity size={15} />
          <div>
            <strong>{sidebarStatus.workerStatus}</strong>
            <span>{sidebarStatus.modelStatus}</span>
          </div>
        </div>
        <nav>
          {nav.map((item) => {
            const Icon = item.icon;
            const active =
              pathname === item.href ||
              (item.href === "/brain" && pathname === "/") ||
              item.aliases?.some((alias) => pathname === alias || pathname.startsWith(`${alias}/`)) ||
              pathname.startsWith(`${item.href}/`);
            return (
              <Link href={item.href} key={item.href} className={clsx("nav-item", active && "active")}>
                <Icon size={17} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="system-card">
          <div><Activity size={15} /> Worker: {sidebarStatus.workerStatus}</div>
          <div><Cpu size={15} /> Model: {sidebarStatus.modelStatus}</div>
          <div><Clock size={15} /> Last learning: {sidebarStatus.lastLearningCycle}</div>
          <div><Copy size={15} /> Paper forward: {sidebarStatus.paperForwardStatus}</div>
          <div><Brain size={15} /> Alpha evidence: {sidebarStatus.alphaEvidenceGrade}</div>
          <span>v{systemStatus?.app_version ?? "loading"}</span>
        </div>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}

function compactStatus(value: any) {
  if (!value) return "pending";
  const text = String(value);
  if (text.includes("T")) {
    try {
      return new Date(text).toLocaleDateString();
    } catch {
      return text;
    }
  }
  return text.replaceAll("_", " ").slice(0, 28);
}
