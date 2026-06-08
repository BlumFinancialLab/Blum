"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Signal } from "@/lib/types";
import { LoadingState } from "@/components/LoadingState";
import { SignalTable } from "@/components/SignalTable";

export default function SignalLabPage() {
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [assetType, setAssetType] = useState("");
  const [risk, setRisk] = useState("");
  const [classification, setClassification] = useState("");
  useEffect(() => { api.topSignals("?limit=80").then(setSignals); }, []);
  const filtered = useMemo(() => {
    return (signals ?? []).filter((signal) =>
      (!assetType || signal.asset?.asset_type === assetType) &&
      (!risk || signal.risk_level === risk) &&
      (!classification || signal.classification === classification)
    );
  }, [signals, assetType, risk, classification]);
  if (!signals) return <LoadingState label="Loading signal lab" />;
  return (
    <>
      <div className="page-header">
        <div><div className="kicker">Signal Lab</div><h1>Filter, compare and audit signal logic.</h1></div>
      </div>
      <div className="control-row">
        <select className="input" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
          <option value="">All asset types</option><option value="Stock">Stock</option><option value="ETF">ETF</option>
        </select>
        <select className="input" value={risk} onChange={(e) => setRisk(e.target.value)}>
          <option value="">All risks</option><option>Low</option><option>Medium</option><option>High</option>
        </select>
        <select className="input" value={classification} onChange={(e) => setClassification(e.target.value)}>
          <option value="">All classifications</option>
          {Array.from(new Set(signals.map((s) => s.classification))).map((item) => <option key={item}>{item}</option>)}
        </select>
      </div>
      <SignalTable signals={filtered} />
    </>
  );
}

