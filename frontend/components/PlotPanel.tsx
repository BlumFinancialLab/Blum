"use client";

import dynamic from "next/dynamic";
import { createElement } from "react";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false }) as any;

type PlotPanelProps = {
  title: string;
  data: any[];
  layout?: Record<string, any>;
  height?: number;
};

export function PlotPanel({ title, data, layout = {}, height = 360 }: PlotPanelProps) {
  const plotProps = {
    data,
    layout: {
      autosize: true,
      height,
      paper_bgcolor: "#07090d",
      plot_bgcolor: "#090d13",
      font: { color: "#e7edf6", family: "Inter, system-ui, sans-serif" },
      margin: { l: 42, r: 18, t: 18, b: 36 },
      xaxis: { gridcolor: "rgba(255,255,255,.06)", zeroline: false },
      yaxis: { gridcolor: "rgba(255,255,255,.06)", zeroline: false },
      ...layout
    },
    config: { displayModeBar: false, responsive: true },
    useResizeHandler: true,
    style: { width: "100%" }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <span>{title}</span>
      </div>
      {createElement(Plot, plotProps)}
    </section>
  );
}
