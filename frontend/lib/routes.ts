export function assetPath(ticker: string) {
  return `/assets/${tickerToAssetSlug(ticker)}`;
}

export function tickerToAssetSlug(ticker: string) {
  return encodeURIComponent(ticker.toUpperCase().replaceAll(".", "_"));
}

export function tickerFromAssetSlug(slug: string) {
  return decodeURIComponent(slug).replaceAll("_", ".").toUpperCase();
}
