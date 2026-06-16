"use client";

import { CommunitySentimentPayload } from "@/lib/types";

export function SentimentTrends({ sentiment }: { sentiment: CommunitySentimentPayload }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <span>Community & Sentiment Intelligence</span>
        <strong>{sentiment.average_sentiment.toFixed(2)}</strong>
      </div>
      <div className="sentiment-columns">
        <div>
          <span>Rising themes</span>
          {sentiment.themes_rising.slice(0, 5).map((theme) => <p key={theme.theme}>{theme.theme} / {theme.headline_count}</p>)}
        </div>
        <div>
          <span>Falling themes</span>
          {sentiment.themes_falling.slice(0, 5).map((theme) => <p key={theme.theme}>{theme.theme} / {theme.avg_sentiment.toFixed(2)}</p>)}
        </div>
        <div>
          <span>Most discussed</span>
          {sentiment.most_discussed_assets.slice(0, 6).map((item) => <p key={item.ticker}>{item.ticker} / {item.discussion_count} mentions / {item.hype_bubble_risk}</p>)}
        </div>
      </div>
      <p>{sentiment.rank_change_policy}</p>
    </div>
  );
}

