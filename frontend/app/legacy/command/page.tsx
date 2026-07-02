import Link from "next/link";

export default function LegacyCommandPage() {
  return (
    <section className="terminal-section">
      <div className="terminal-card">
        <div className="kicker">Legacy / Dev Tool</div>
        <h1>Legacy Command surface is no longer the primary BLUM product.</h1>
        <p>
          The primary product surface is now Trader Brain. Legacy research and diagnostic pages remain
          available by direct URL for development, but they are intentionally hidden from the main navigation.
        </p>
        <div className="terminal-actions">
          <Link className="button primary" href="/brain">Open Brain</Link>
          <Link className="button" href="/performance">Developer diagnostics</Link>
          <Link className="button" href="/stock-radar">Legacy radar</Link>
        </div>
      </div>
    </section>
  );
}
