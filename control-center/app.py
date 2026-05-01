#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
REPORT_DIR = PROJECT_ROOT / "reports"
BOT_LOGS = {
    "Crypto": LOG_DIR / "crypto",
    "Options": LOG_DIR / "options",
    "Quantum AI": LOG_DIR / "quantum-ai",
    "Private AI": LOG_DIR / "private-ai",
}
SUMMARY_REPORT = REPORT_DIR / "backtests/ALL_PRODUCTS_strategy_category_summary.csv"

EQUITY_METRICS = (
    ("equity", "Equity"),
    ("current_equity", "Current Equity"),
    ("cash", "Cash"),
    ("open_value", "Open Value"),
    ("daily_pl", "Daily P/L"),
    ("daily_pl_pct", "Daily P/L %"),
    ("realized_pl", "Realized P/L"),
    ("realized_pl_total", "Realized P/L Total"),
    ("realized_pl_today", "Realized P/L Today"),
    ("unrealized_pl", "Unrealized P/L"),
    ("open_positions", "Open Positions"),
    ("trading_halted", "Trading Halted"),
    ("halted", "Halted"),
    ("halt_reason", "Halt Reason"),
)
SCAN_METRICS = (
    ("symbol", "Symbol"),
    ("asset_type", "Asset Type"),
    ("price", "Price"),
    ("action", "Action"),
    ("consensus", "Consensus"),
    ("bull_score", "Bull Score"),
    ("bear_score", "Bear Score"),
    ("bullish_score", "Bullish Score"),
    ("bearish_score", "Bearish Score"),
    ("rsi14", "RSI 14"),
    ("candidate_strategy", "Candidate Strategy"),
    ("candidate_contract", "Candidate Contract"),
    ("news_article_count", "News Articles"),
    ("news_risk_hits", "News Risk Hits"),
    ("news_positive_hits", "News Positive Hits"),
)
CRYPTO_ALPHA_METRICS = (
    ("benchmark_btc_equity", "BTC Benchmark"),
    ("benchmark_eth_equity", "ETH Benchmark"),
    ("benchmark_sol_equity", "SOL Benchmark"),
    ("benchmark_equal_weight_equity", "Equal Weight Benchmark"),
    ("alpha_vs_btc_usd", "Alpha vs BTC"),
    ("alpha_vs_eth_usd", "Alpha vs ETH"),
    ("alpha_vs_sol_usd", "Alpha vs SOL"),
    ("alpha_vs_equal_weight_usd", "Alpha vs Equal Weight"),
)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_last_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    last: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                last = {key: value for key, value in row.items() if key}
    except OSError:
        return {}
    return last


def read_csv_rows(path: Path, limit: int = 20) -> list[dict[str, str]]:
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rows.append({key: value for key, value in row.items() if key})
    except OSError:
        return []
    return rows[-limit:]


def short_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value
        if number.is_integer():
            return f"{number:,.0f}"
        return f"{number:,.2f}"
    return str(value)


def display_value(key: str, value: object) -> str:
    if value in (None, ""):
        return ""
    if key.endswith("_pct") and isinstance(value, str):
        try:
            return f"{float(value):,.2f}%"
        except ValueError:
            return value
    return short_value(value)


def metric_spans(source: dict[str, object], fields: tuple[tuple[str, str], ...]) -> list[str]:
    metrics = []
    for key, label in fields:
        value = display_value(key, source.get(key))
        if value:
            metrics.append(f"<span>{html.escape(label)}: <b>{html.escape(value)}</b></span>")
    return metrics


def list_recent_files(root: Path, limit: int = 12) -> list[Path]:
    if not root.exists():
        return []
    files = [path for path in root.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def log_file_link(path: Path) -> str:
    rel = path.relative_to(LOG_DIR).as_posix()
    href = f"/download?root=logs&path={quote(rel)}"
    return f'<a href="{html.escape(href)}">{html.escape(path.name)}</a>'


def bot_cards() -> str:
    cards = []
    for name, log_dir in BOT_LOGS.items():
        state_files = sorted(log_dir.glob("*state*.json"))
        equity_files = sorted(log_dir.glob("*equity*.csv"))
        scan_files = sorted(log_dir.glob("*scan*.csv"))
        daily_files = sorted(log_dir.glob("*daily*.csv"))
        news_files = sorted(log_dir.glob("*news*.csv"))
        state = read_json(state_files[0]) if state_files else {}
        equity = read_last_csv_row(equity_files[0]) if equity_files else {}
        daily = read_last_csv_row(daily_files[0]) if daily_files else {}
        scan = read_last_csv_row(scan_files[0]) if scan_files else {}
        news = read_last_csv_row(news_files[0]) if news_files else {}
        updated = max(
            [
                path.stat().st_mtime
                for path in [*state_files, *equity_files, *scan_files, *daily_files, *news_files]
                if path.exists()
            ],
            default=0,
        )
        status = "Ready" if log_dir.exists() else "Missing"
        equity_source = {**state, **daily, **equity}
        scan_source = {**scan, **news}
        equity_metrics = metric_spans(equity_source, EQUITY_METRICS)
        scan_metrics = metric_spans(scan_source, SCAN_METRICS)
        alpha_metrics = metric_spans(equity_source, CRYPTO_ALPHA_METRICS) if name == "Crypto" else []
        latest_timestamp = equity.get("timestamp_local") or scan.get("timestamp_local") or news.get("timestamp_local")
        file_links = [log_file_link(path) for path in [*state_files, *equity_files, *daily_files, *scan_files, *news_files]]
        if not equity_metrics and not scan_metrics and not alpha_metrics:
            equity_metrics = ["<span>No recent log rows yet</span>"]
        updated_label = "No files" if updated == 0 else f"{int(updated)}"
        cards.append(
            f"""
            <article class="card">
              <div class="card-head">
                <h2>{html.escape(name)}</h2>
                <span class="pill">{status}</span>
              </div>
              <div class="metric-block">
                <h3>Account</h3>
                <div class="metrics">{''.join(equity_metrics[:8])}</div>
              </div>
              <div class="metric-block">
                <h3>Latest Scan</h3>
                <div class="metrics">{''.join(scan_metrics[:8]) or '<span>No scan row yet</span>'}</div>
              </div>
              {f'<div class="metric-block"><h3>Benchmarks</h3><div class="metrics">{"".join(alpha_metrics[:8])}</div></div>' if alpha_metrics else ''}
              <div class="file-links">{' '.join(file_links) or 'No log files'}</div>
              {f'<span class="mtime">Latest row: {html.escape(latest_timestamp)}</span>' if latest_timestamp else ''}
              <span class="mtime" data-mtime="{updated_label}"></span>
            </article>
            """
        )
    return "\n".join(cards)


def recent_file_list(root_name: str, root: Path) -> str:
    items = []
    for path in list_recent_files(root):
        rel = path.relative_to(root).as_posix()
        href = f"/download?root={root_name}&path={quote(rel)}"
        items.append(f'<li><a href="{html.escape(href)}">{html.escape(rel)}</a></li>')
    if not items:
        items.append("<li>No files yet</li>")
    return "\n".join(items)


def render_backtest_summary() -> str:
    rows = read_csv_rows(SUMMARY_REPORT, limit=200)
    if not rows:
        return "<p>No aggregate backtest summary is available yet.</p>"
    promoted = [row for row in rows if row.get("decision_note") == "category_positive_out_of_sample"]
    display_rows = promoted or rows[:10]
    items = []
    for row in display_rows[:10]:
        product = row.get("product", "")
        strategy = row.get("strategy", "")
        after_tax = display_value("total_after_tax_pl", row.get("total_after_tax_pl"))
        alpha = display_value("mean_alpha_pct", row.get("mean_alpha_pct"))
        trades = display_value("total_trades", row.get("total_trades"))
        decision = row.get("decision_note", "")
        items.append(
            "<tr>"
            f"<td>{html.escape(product)}</td>"
            f"<td>{html.escape(strategy)}</td>"
            f"<td>{html.escape(after_tax)}</td>"
            f"<td>{html.escape(alpha)}</td>"
            f"<td>{html.escape(trades)}</td>"
            f"<td>{html.escape(decision)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Product</th><th>Strategy</th><th>After-Tax P/L</th>"
        "<th>Mean Alpha %</th><th>Trades</th><th>Decision</th></tr></thead>"
        f"<tbody>{''.join(items)}</tbody></table>"
    )


def render_dashboard() -> bytes:
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InvestAI Control Center</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172026;
      --muted: #5d6972;
      --line: #d9dee2;
      --panel: #ffffff;
      --page: #f5f7f8;
      --accent: #0f766e;
      --accent-2: #334155;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--page); color: var(--ink); font: 15px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; }}
    header {{ background: #fff; border-bottom: 1px solid var(--line); padding: 20px clamp(16px, 4vw, 36px); }}
    h1 {{ margin: 0; font-size: 28px; letter-spacing: 0; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 24px clamp(16px, 4vw, 36px) 40px; }}
    .subhead {{ margin: 6px 0 0; color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 14px; }}
    .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-height: 172px; display: flex; flex-direction: column; gap: 14px; }}
    .card-head {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; }}
    h2 {{ margin: 0; font-size: 18px; }}
    .pill {{ border: 1px solid #99c9c3; color: #075e56; border-radius: 999px; padding: 2px 9px; font-size: 12px; }}
    .metric-block {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .metric-block:first-of-type {{ border-top: 0; padding-top: 0; }}
    .metric-block h3 {{ margin: 0 0 7px; font-size: 13px; color: var(--accent-2); text-transform: uppercase; }}
    .metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 5px 12px; color: var(--muted); }}
    a {{ color: var(--accent); text-decoration: none; font-weight: 650; }}
    a:hover {{ text-decoration: underline; }}
    section {{ margin-top: 24px; }}
    .lists {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
    .list-panel {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
    h3 {{ margin: 0 0 10px; font-size: 16px; color: var(--accent-2); }}
    ul {{ margin: 0; padding-left: 18px; }}
    li {{ margin: 6px 0; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 8px 6px; text-align: left; vertical-align: top; }}
    th {{ color: var(--accent-2); font-size: 12px; text-transform: uppercase; }}
    .file-links {{ display: flex; flex-wrap: wrap; gap: 8px; font-size: 12px; }}
    .mtime {{ color: var(--muted); font-size: 12px; margin-top: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>InvestAI Control Center</h1>
    <p class="subhead">Local paper-trading status from logs and backtest reports.</p>
  </header>
  <main>
    <div class="grid">{bot_cards()}</div>
    <section class="list-panel">
      <h3>Backtest Category Summary</h3>
      {render_backtest_summary()}
    </section>
    <section class="lists">
      <div class="list-panel">
        <h3>Recent Logs</h3>
        <ul>{recent_file_list("logs", LOG_DIR)}</ul>
      </div>
      <div class="list-panel">
        <h3>Recent Reports</h3>
        <ul>{recent_file_list("reports", REPORT_DIR)}</ul>
      </div>
    </section>
  </main>
  <script>
    for (const node of document.querySelectorAll("[data-mtime]")) {{
      const raw = Number(node.dataset.mtime);
      node.textContent = raw ? "Updated " + new Date(raw * 1000).toLocaleString() : "No files";
    }}
  </script>
</body>
</html>"""
    return body.encode("utf-8")


def safe_path(root: Path, requested: str) -> Path | None:
    target = (root / unquote(requested)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status: int, content: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(200, render_dashboard())
            return
        if parsed.path == "/download":
            params = parse_qs(parsed.query)
            roots = {"logs": LOG_DIR, "reports": REPORT_DIR}
            root = roots.get(params.get("root", [""])[0])
            if root is None:
                self.send_bytes(404, b"Unknown root", "text/plain; charset=utf-8")
                return
            target = safe_path(root, params.get("path", [""])[0])
            if target is None or not target.is_file():
                self.send_bytes(404, b"File not found", "text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(target.name)[0] or "text/plain"
            self.send_bytes(200, target.read_bytes(), content_type)
            return
        if parsed.path == "/files":
            params = parse_qs(parsed.query)
            roots = {"logs": LOG_DIR, "reports": REPORT_DIR}
            root = roots.get(params.get("root", [""])[0])
            target = safe_path(root, params.get("path", [""])[0]) if root else None
            if target is None or not target.exists():
                self.send_bytes(404, b"Folder not found", "text/plain; charset=utf-8")
                return
            names = "\n".join(html.escape(path.name) for path in sorted(target.iterdir()))
            self.send_bytes(200, f"<pre>{names}</pre>".encode("utf-8"))
            return
        self.send_bytes(404, b"Not found", "text/plain; charset=utf-8")

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local InvestAI control center.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"InvestAI control center listening on http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInvestAI control center stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
