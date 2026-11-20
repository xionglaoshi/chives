"""Tiny local fake of the FMP stable API used only by the offline tests."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

INCOME = [
    {
        "date": "2025-09-27",
        "symbol": "AAPL",
        "reportedCurrency": "USD",
        "fiscalYear": "2025",
        "period": "FY",
        "revenue": 416161000000,
        "netIncome": 112010000000,
    },
    {
        "date": "2024-09-28",
        "symbol": "AAPL",
        "reportedCurrency": "USD",
        "fiscalYear": "2024",
        "period": "FY",
        "revenue": 391035000000,
        "netIncome": 93736000000,
    },
]

FIXED: dict[str, list[dict[str, Any]]] = {
    "/stable/search-symbol": [
        {"symbol": "AAPL", "name": "Apple Inc.", "currency": "USD", "exchange": "NASDAQ"}
    ],
    "/stable/search-name": [
        {"symbol": "AAPL", "name": "Apple Inc.", "currency": "USD", "exchange": "NASDAQ"},
        {"symbol": "APLE", "name": "Apple Hospitality REIT", "currency": "USD", "exchange": "NYSE"},
    ],
    "/stable/quote": [
        {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "price": 200.5,
            "changePercentage": 1.2,
            "volume": 12345678,
            "timestamp": 1793613041,
        }
    ],
    "/stable/profile": [
        {"symbol": "AAPL", "companyName": "Apple Inc.", "price": 200.5, "currency": "USD"}
    ],
    "/stable/income-statement": INCOME,
    "/stable/balance-sheet-statement": [
        {"date": "2025-09-27", "symbol": "AAPL", "reportedCurrency": "USD", "totalAssets": 359241000000}
    ],
    "/stable/cash-flow-statement": [
        {"date": "2025-09-27", "symbol": "AAPL", "reportedCurrency": "USD", "operatingCashFlow": 111482000000}
    ],
    "/stable/ratios": [{"symbol": "AAPL", "fiscalYear": "2025", "grossProfitMargin": 0.46}],
    "/stable/key-metrics": [{"symbol": "AAPL", "fiscalYear": "2025", "marketCap": 3000000000000}],
    "/stable/analyst-estimates": [{"symbol": "AAPL", "date": "2026-09-30", "epsAvg": 7.9}],
    "/stable/price-target-summary": [{"symbol": "AAPL", "lastMonthAvgPriceTarget": 230.5}],
    "/stable/grades": [{"symbol": "AAPL", "gradingCompany": "TestBank", "newGrade": "Buy"}],
    "/stable/insider-trading/search": [
        {"symbol": "AAPL", "reportingName": "Test Person", "transactionType": "S-Sale"}
    ],
    "/stable/earnings-calendar": [{"symbol": "AAPL", "date": "2026-10-29", "epsEstimated": 1.9}],
    "/stable/historical-price-eod/full": [
        {"symbol": "AAPL", "date": "2026-10-30", "open": 198.0, "close": 200.5, "volume": 50000000}
    ],
    "/stable/shares-float": [{"symbol": "AAPL", "floatShares": 14569078010}],
    "/stable/stock-peers": [{"symbol": "MSFT", "companyName": "Microsoft"}],
}


MANY = [
    {"symbol": "AAPL", "date": f"2026-10-{i:02d}", "gradingCompany": f"Bank{i}", "newGrade": "Buy"}
    for i in range(1, 9)
]
MANY_BIG = [{"symbol": "AAPL", "i": i, "close": 200.5} for i in range(250)]


class FakeFmp:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        owner = self
        self.port = 0

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                owner.requests.append(
                    {
                        "path": parsed.path,
                        "query": query,
                        "header_apikey": bool(self.headers.get("apikey")),
                    }
                )
                key = query.get("apikey") or self.headers.get("apikey") or ""
                symbol = (query.get("symbol") or query.get("query") or "").upper()
                if not key:
                    return self._send(401, {"Error Message": "Invalid API KEY."})
                if symbol == "BADKEY":
                    return self._send(
                        401,
                        {"Error Message": f"Invalid API KEY. request: {self.path} key={key}"},
                    )
                if symbol == "ECHO500":
                    return self._send(500, {"Error Message": f"upstream exploded at {self.path} key={key}"})
                if symbol == "ERR200":
                    return self._send(200, {"Error Message": f"Invalid API KEY. key={key}"})
                if symbol == "LIMIT":
                    return self._send(429, {"Error Message": "Limit Reach. Please upgrade your plan"})
                if symbol == "PREMIUM":
                    return self._send(402, {"Error Message": "Premium endpoint: missing subscription"})
                if symbol == "FAIL500":
                    return self._send(500, {"Error Message": "boom"})
                if symbol == "REDIRECT":
                    return self._send(302, {}, {"Location": "https://example.com/elsewhere"})
                if symbol == "SLOW":
                    time.sleep(2)
                    return self._send(200, FIXED["/stable/quote"])
                if symbol == "ZZZZ":
                    return self._send(200, [])
                if symbol == "MANY" and parsed.path in (
                    "/stable/grades",
                    "/stable/insider-trading/search",
                ):
                    return self._send(200, MANY)  # ignores limit, like the real /grades endpoint
                if symbol == "MANY" and parsed.path == "/stable/historical-price-eod/full":
                    return self._send(200, MANY_BIG)
                if parsed.path in FIXED:
                    rows = FIXED[parsed.path]
                    limit = query.get("limit", "")
                    if limit.isdigit():
                        rows = rows[: int(limit)]
                    return self._send(200, rows)
                return self._send(404, {"Error Message": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
