"use client";

import { WatchlistPayload } from "@/lib/types";

export function Watchlist({ watchlist }: { watchlist: WatchlistPayload }) {
  const items = watchlist.items.length ? watchlist.items : watchlist.suggested_items ?? [];
  return (
    <div className="panel watchlist-panel">
      <div className="panel-head">
        <span>Watchlist Alerts</span>
        <strong>{watchlist.alerts.length}</strong>
      </div>
      <div className="watchlist-feed">
        {watchlist.alerts.slice(0, 6).map((alert) => (
          <div key={`${alert.ticker}-${alert.message}`}>
            <strong>{alert.ticker}</strong>
            <span>{alert.message}</span>
          </div>
        ))}
        {!watchlist.alerts.length && <div className="empty-state">No watchlist alerts yet. Suggested monitor candidates are shown below.</div>}
      </div>
      <div className="tag-row">
        {items.slice(0, 8).map((item: any) => <span key={item.ticker}>{item.ticker}</span>)}
      </div>
    </div>
  );
}

