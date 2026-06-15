import { AssetDetailClient } from "./view";
import { tickerFromAssetSlug, tickerToAssetSlug } from "@/lib/routes";

const tickers = [
  "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XAR", "BOTZ", "HACK", "ICLN", "TLT", "GLD",
  "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "LLY", "NVO", "ASML", "SAP",
  "SIE.DE", "AIR.PA", "RHM.DE", "MC.PA", "ENR.DE"
];

export function generateStaticParams() {
  return tickers.map((ticker) => ({ ticker: tickerToAssetSlug(ticker) }));
}

export default function AssetDetailPage({ params }: { params: { ticker: string } }) {
  return <AssetDetailClient ticker={tickerFromAssetSlug(params.ticker)} />;
}
