"""News providers — each source normalized to NewsItem format.

Every provider implements: fetch(symbols, **kwargs) -> list[NewsItem]
The NewsAgent orchestrates them and merges the results.

Providers:
  1. YFinanceProvider    — per-stock news, analyst recs, insider, earnings (free)
  2. RSSProvider         — Yahoo Finance RSS headlines (free, fragile)
  3. MarketauxProvider   — entity-linked market news (free tier: 100 req/day)
  4. SECEdgarProvider    — 8-K, Form 4, 13D/13G filings (free, no key)
  5. FREDProvider        — macro regime data: VIX, yields, spreads (free key)
  6. FinnhubProvider     — social sentiment, insider trades, analyst trends (free: 60/min)
  7. AlphaVantageProvider — NLP news sentiment with ticker relevance (free: 25/day)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
import yfinance as yf

from agent_trader.utils.news_types import (
    NewsItem,
    score_headline,
    extract_tickers,
)
from agent_trader.utils.runtime import configure_yfinance_cache


# ══════════════════════════════════════════════════════════════
# 1. YFinance Provider
# ══════════════════════════════════════════════════════════════

class YFinanceProvider:
    """Per-stock news, analyst recs, insider activity, earnings dates."""

    name = "yfinance"

    def __init__(self):
        configure_yfinance_cache()

    def is_available(self) -> bool:
        return True

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        items: list[NewsItem] = []
        for symbol in symbols:
            items.extend(self._fetch_stock_news(symbol))
        return items

    def fetch_analyst_data(self, symbol: str) -> dict | None:
        """Fetch analyst consensus — separate from headlines."""
        try:
            ticker = yf.Ticker(symbol)
            recs = ticker.recommendations_summary
            if recs is None or recs.empty:
                return None

            row = recs.iloc[0]
            strong_buy = int(row.get("strongBuy", 0))
            buy = int(row.get("buy", 0))
            hold = int(row.get("hold", 0))
            sell = int(row.get("sell", 0))
            strong_sell = int(row.get("strongSell", 0))

            total = strong_buy + buy + hold + sell + strong_sell
            if total == 0:
                return None

            score = (
                (strong_buy * 2 + buy * 1 + hold * 0 + sell * -1 + strong_sell * -2)
                / (total * 2)
            )

            return {
                "strong_buy": strong_buy, "buy": buy, "hold": hold,
                "sell": sell, "strong_sell": strong_sell, "total": total,
                "consensus_score": round(score, 2),
                "consensus": (
                    "strong_buy" if score > 0.5 else
                    "buy" if score > 0.15 else
                    "hold" if score > -0.15 else
                    "sell" if score > -0.5 else
                    "strong_sell"
                ),
            }
        except Exception:
            return None

    def fetch_insider_activity(self, symbol: str) -> dict | None:
        """Check recent insider buying/selling."""
        try:
            ticker = yf.Ticker(symbol)
            insiders = ticker.insider_transactions
            if insiders is None or insiders.empty:
                return None

            recent = insiders.head(10)
            buys = sells = 0
            for _, row in recent.iterrows():
                text = str(row.get("Text", "")).lower()
                if "purchase" in text or "buy" in text:
                    buys += 1
                elif "sale" in text or "sell" in text:
                    sells += 1

            if buys == 0 and sells == 0:
                return None

            return {
                "recent_buys": buys, "recent_sells": sells,
                "signal": (
                    "insider_buying" if buys > sells else
                    "insider_selling" if sells > buys else
                    "mixed"
                ),
            }
        except Exception:
            return None

    def fetch_earnings_proximity(self, symbol: str) -> dict | None:
        """Check how close a stock is to its earnings date."""
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if not cal or not isinstance(cal, dict):
                return None

            earnings_date = cal.get("Earnings Date")
            if not earnings_date:
                return None

            if isinstance(earnings_date, list):
                earnings_date = earnings_date[0]

            now = datetime.now(timezone.utc)
            if hasattr(earnings_date, "timestamp"):
                days_until = (earnings_date - now).days
            else:
                return {"date": str(earnings_date), "days_until": None}

            return {
                "date": str(earnings_date),
                "days_until": days_until,
                "warning": days_until <= 5,
                "type": "earnings",
            }
        except Exception:
            return None

    def fetch_upgrades_downgrades(self, symbols: list[str]) -> list[NewsItem]:
        """Fetch recent analyst upgrades/downgrades as NewsItems."""
        items: list[NewsItem] = []
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                upgrades = ticker.upgrades_downgrades
                if upgrades is None or upgrades.empty:
                    continue

                for _, row in upgrades.head(3).iterrows():
                    action = str(row.get("Action", "")).lower()
                    if "upgrade" not in action and "downgrade" not in action:
                        continue

                    firm = str(row.get("Firm", ""))
                    from_grade = str(row.get("FromGrade", ""))
                    to_grade = str(row.get("ToGrade", ""))

                    sentiment = 0.5 if "upgrade" in action else -0.5
                    items.append(NewsItem(
                        title=f"{firm}: {action} {symbol} ({from_grade} -> {to_grade})",
                        source="yfinance",
                        published="",
                        symbols=[symbol],
                        sentiment=sentiment,
                        category="analyst",
                        publisher=firm,
                        metadata={"action": action, "from": from_grade, "to": to_grade},
                    ))
            except Exception:
                continue
        return items

    def _fetch_stock_news(self, symbol: str) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news
            if not news:
                return items

            for raw_item in news[:8]:
                parsed = _parse_yfinance_news_item(raw_item)
                title = parsed["title"]
                if not title:
                    continue

                items.append(NewsItem(
                    title=title,
                    source="yfinance",
                    published=parsed["published"],
                    symbols=[symbol],
                    sentiment=score_headline(title),
                    category="headline",
                    url=parsed["url"],
                    summary=parsed["summary"][:300],
                    publisher=parsed["publisher"],
                    metadata={"type": parsed["type"]},
                ))
        except Exception:
            pass
        return items


# ══════════════════════════════════════════════════════════════
# 2. RSS Provider
# ══════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "yahoo_market": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
    "yahoo_tech": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^NDX&region=US&lang=en-US",
    "yahoo_trending": "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US",
}


class RSSProvider:
    """Yahoo Finance RSS headlines."""

    name = "rss"

    def __init__(self):
        self._http = httpx.Client(timeout=10, follow_redirects=True)

    def is_available(self) -> bool:
        return True

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        known_tickers = kwargs.get("known_tickers")
        items = self._fetch_rss_feeds(known_tickers)
        if not items:
            items = self._fetch_fallback(known_tickers)
        return items

    def _fetch_rss_feeds(self, known_tickers: set[str] | None) -> list[NewsItem]:
        items: list[NewsItem] = []
        seen_titles: set[str] = set()

        for feed_name, url in RSS_FEEDS.items():
            try:
                response = self._http.get(url)
                if response.status_code != 200:
                    continue

                root = ET.fromstring(response.text)
                channel = root.find("channel")
                if channel is None:
                    continue

                for entry in channel.findall("item")[:10]:
                    title = entry.findtext("title", "")
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    pub_date = entry.findtext("pubDate", "")
                    link = entry.findtext("link", "")
                    description = entry.findtext("description", "")
                    mentioned = extract_tickers(
                        title + " " + description,
                        known_tickers,
                    )

                    items.append(NewsItem(
                        title=title,
                        source="rss",
                        published=pub_date,
                        symbols=mentioned,
                        sentiment=score_headline(title),
                        category="headline",
                        url=link,
                        summary=description[:200] if description else "",
                        publisher=feed_name,
                    ))
            except Exception:
                continue

        return items[:20]

    def _fetch_fallback(self, known_tickers: set[str] | None) -> list[NewsItem]:
        """Fallback: pull headlines from broad market ETFs."""
        configure_yfinance_cache()
        items: list[NewsItem] = []
        seen_titles: set[str] = set()

        for symbol in ["SPY", "QQQ", "DIA", "IWM", "XLK", "XLF"]:
            try:
                ticker = yf.Ticker(symbol)
                news = ticker.news or []
                for raw in news[:4]:
                    parsed = _parse_yfinance_news_item(raw)
                    title = parsed["title"]
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    mentioned = extract_tickers(
                        title + " " + parsed["summary"],
                        known_tickers,
                    )
                    if symbol not in mentioned:
                        mentioned.append(symbol)

                    items.append(NewsItem(
                        title=title,
                        source="rss",
                        published=parsed["published"],
                        symbols=mentioned,
                        sentiment=score_headline(title),
                        category="headline",
                        url=parsed["url"],
                        summary=parsed["summary"][:200],
                        publisher=f"yfinance:{symbol}",
                    ))
            except Exception:
                continue

        return items[:20]


# ══════════════════════════════════════════════════════════════
# 3. Marketaux Provider
# ══════════════════════════════════════════════════════════════

class MarketauxProvider:
    """Entity-linked market news via Marketaux API.

    Free tier: 100 requests/day, 3 articles per request.
    We use it surgically — only for shortlisted stocks and hot topics.
    """

    name = "marketaux"
    _BASE = "https://api.marketaux.com/v1/news/all"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._http = httpx.Client(timeout=15, follow_redirects=True)

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        if not self._api_key:
            return []

        items: list[NewsItem] = []

        # Batch symbols in groups of 5 (API supports comma-separated)
        for i in range(0, len(symbols), 5):
            batch = symbols[i : i + 5]
            batch_items = self._fetch_batch(batch)
            items.extend(batch_items)

        return items

    def fetch_broad(self, **kwargs) -> list[NewsItem]:
        """Broad market news scan — filtered to financial content only."""
        if not self._api_key:
            return []
        return self._fetch_batch([], limit=3, financial_only=True)

    def _fetch_batch(
        self, symbols: list[str], limit: int = 3, financial_only: bool = False
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            params: dict = {
                "api_token": self._api_key,
                "language": "en",
                "limit": limit,
                "filter_entities": "true",
            }
            if symbols:
                params["symbols"] = ",".join(symbols)
            if financial_only or not symbols:
                # Restrict to financial/business content when doing broad scans
                params["industries"] = "Technology,Finance,Energy,Healthcare"
                params["must_have_entities"] = "true"

            response = self._http.get(self._BASE, params=params)
            if response.status_code != 200:
                return items

            data = response.json()
            for article in data.get("data", []):
                title = article.get("title", "")
                if not title:
                    continue

                # Extract symbols and per-entity sentiment from entity list
                article_symbols = []
                entity_sentiments: dict[str, float] = {}
                for entity in article.get("entities", []):
                    sym = entity.get("symbol")
                    if sym:
                        article_symbols.append(sym)
                        # Marketaux provides per-entity sentiment_score
                        ent_sent = entity.get("sentiment_score")
                        if ent_sent is not None:
                            entity_sentiments[sym] = float(ent_sent)

                # Use per-entity sentiment average (most accurate),
                # fall back to article-level, then keyword scoring
                sentiment_score = 0.0
                if entity_sentiments:
                    sentiment_score = sum(entity_sentiments.values()) / len(entity_sentiments)
                else:
                    raw_sentiment = article.get("sentiment")
                    if raw_sentiment:
                        if isinstance(raw_sentiment, (int, float)):
                            sentiment_score = float(raw_sentiment)
                        elif isinstance(raw_sentiment, str):
                            sentiment_score = {
                                "positive": 0.5, "negative": -0.5,
                                "neutral": 0.0, "bullish": 0.6,
                                "bearish": -0.6,
                            }.get(raw_sentiment.lower(), 0.0)

                if sentiment_score == 0.0:
                    sentiment_score = score_headline(title)

                # Clamp to [-1, 1]
                sentiment_score = max(-1.0, min(1.0, round(sentiment_score, 3)))

                highlights = article.get("highlights", [])
                summary = highlights[0] if highlights else article.get("description", "")

                items.append(NewsItem(
                    title=title,
                    source="marketaux",
                    published=article.get("published_at", ""),
                    symbols=article_symbols or symbols,
                    sentiment=sentiment_score,
                    category="headline",
                    url=article.get("url", ""),
                    summary=str(summary)[:300] if summary else "",
                    publisher=article.get("source", ""),
                    metadata={
                        "entities": article.get("entities", []),
                        "relevance_score": article.get("relevance_score"),
                    },
                ))
        except Exception:
            pass

        return items


# ══════════════════════════════════════════════════════════════
# 4. SEC EDGAR Provider
# ══════════════════════════════════════════════════════════════

# CIK lookup for the stocks we care about — EDGAR uses CIK, not tickers
# This covers the main screener universe. We also do dynamic lookup.
_CIK_CACHE: dict[str, str] = {}


class SECEdgarProvider:
    """SEC EDGAR filings — 8-K (material events), Form 4 (insider trades),
    13D/13G (activist positions).

    Free, no API key. SEC asks for a declared User-Agent header.
    Fair-access: 10 requests/second.
    """

    name = "sec_edgar"
    _BASE = "https://efts.sec.gov/LATEST/search-index?q="
    _FILINGS_BASE = "https://efts.sec.gov/LATEST/search-index"
    _COMPANY_SEARCH = "https://efts.sec.gov/LATEST/search-index"
    _FULL_TEXT_SEARCH = "https://efts.sec.gov/LATEST/search-index"
    _RSS_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"

    def __init__(self, user_agent: str = ""):
        # SEC requires a declared user-agent for automated access
        self._user_agent = user_agent or "AgentTrader research@example.com"
        self._http = httpx.Client(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"},
        )

    def is_available(self) -> bool:
        return True  # No API key needed

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        items: list[NewsItem] = []
        form_types = kwargs.get("form_types", ["8-K", "4"])

        for symbol in symbols:
            try:
                cik = self._resolve_cik(symbol)
                if not cik:
                    continue

                for form_type in form_types:
                    filings = self._fetch_recent_filings(cik, symbol, form_type)
                    items.extend(filings)
            except Exception:
                continue

        return items

    def _resolve_cik(self, symbol: str) -> str | None:
        """Resolve ticker to CIK via SEC company tickers JSON."""
        if symbol in _CIK_CACHE:
            return _CIK_CACHE[symbol]

        try:
            url = "https://www.sec.gov/files/company_tickers.json"
            response = self._http.get(url)
            if response.status_code != 200:
                return None

            data = response.json()
            for entry in data.values():
                ticker = str(entry.get("ticker", "")).upper()
                cik = str(entry.get("cik_str", ""))
                _CIK_CACHE[ticker] = cik

            return _CIK_CACHE.get(symbol)
        except Exception:
            return None

    def _fetch_recent_filings(
        self, cik: str, symbol: str, form_type: str
    ) -> list[NewsItem]:
        """Fetch recent filings via EDGAR company submissions API.

        Uses data.sec.gov/submissions/ which returns structured JSON
        with accession numbers, filing dates, and form types.
        For Form 4 (insider trades), we also fetch the actual filing
        to determine buy vs sell.
        """
        items: list[NewsItem] = []
        try:
            # Pad CIK to 10 digits for the submissions API
            padded_cik = cik.zfill(10)
            url = f"https://data.sec.gov/submissions/CIK{padded_cik}.json"
            response = self._http.get(url)
            if response.status_code != 200:
                return self._fetch_filings_rss(cik, symbol, form_type)

            data = response.json()
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])

            count = 0
            for i, form in enumerate(forms):
                if form != form_type or count >= 5:
                    continue

                filed = dates[i] if i < len(dates) else ""
                accession = accessions[i] if i < len(accessions) else ""
                primary_doc = primary_docs[i] if i < len(primary_docs) else ""

                # Only look at filings from the last 7 days
                if filed and filed < _days_ago(7):
                    continue

                count += 1
                accession_path = accession.replace("-", "")
                filing_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary_doc}"
                    if primary_doc else
                    f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form_type}&dateb=&owner=include&count=5"
                )

                # For Form 4, try to parse the XML to get buy/sell details
                title_detail = ""
                sentiment = 0.0
                if form_type == "4" and primary_doc and primary_doc.endswith(".xml"):
                    # primaryDocument often has XSL prefix like "xslF345X06/file.xml"
                    # The raw XML is at the root without the prefix
                    raw_doc = primary_doc.split("/")[-1] if "/" in primary_doc else primary_doc
                    tx_info = self._parse_form4_xml(cik, accession_path, raw_doc)
                    if tx_info:
                        title_detail = tx_info["summary"]
                        sentiment = tx_info["sentiment"]

                if not title_detail:
                    title_detail = f"Filed {filed}"
                    sentiment = self._filing_sentiment(form_type, "")

                category = "insider" if form_type == "4" else "filing"
                items.append(NewsItem(
                    title=f"SEC {form}: {symbol} — {title_detail}",
                    source="sec_edgar",
                    published=filed,
                    symbols=[symbol],
                    sentiment=sentiment,
                    category=category,
                    url=filing_url,
                    metadata={"form_type": form, "cik": cik, "accession": accession},
                ))
        except Exception:
            pass

        return items

    def _parse_form4_xml(
        self, cik: str, accession_path: str, primary_doc: str
    ) -> dict | None:
        """Parse a Form 4 XML filing to extract buy/sell transaction details.

        Returns {"summary": str, "sentiment": float} or None.
        """
        try:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary_doc}"
            response = self._http.get(url)
            if response.status_code != 200:
                return None

            root = ET.fromstring(response.text)

            # Get the reporting person's name
            owner_name = ""
            owner_elem = root.find(".//{http://www.sec.gov/cgi-bin/browse-edgar?action=getcompany}reportingOwner")
            if owner_elem is None:
                # Try without namespace
                owner_elem = root.find(".//reportingOwner")
            if owner_elem is not None:
                name_elem = owner_elem.find(".//rptOwnerName")
                if name_elem is not None and name_elem.text:
                    owner_name = name_elem.text.strip()

            # Parse non-derivative transactions
            total_acquired = 0.0
            total_disposed = 0.0
            total_value = 0.0

            for tx in root.iter():
                if "nonDerivativeTransaction" in tx.tag or "derivativeTransaction" in tx.tag:
                    code_elem = tx.find(".//{*}transactionCode")
                    code = code_elem.text.strip() if code_elem is not None and code_elem.text else ""

                    shares_elem = tx.find(".//{*}transactionShares/{*}value")
                    shares = float(shares_elem.text) if shares_elem is not None and shares_elem.text else 0

                    price_elem = tx.find(".//{*}transactionPricePerShare/{*}value")
                    price = float(price_elem.text) if price_elem is not None and price_elem.text else 0

                    ad_elem = tx.find(".//{*}transactionAcquiredDisposedCode/{*}value")
                    ad_code = ad_elem.text.strip() if ad_elem is not None and ad_elem.text else ""

                    value = shares * price

                    # P = open market purchase, S = open market sale
                    # A = grant/award, M = exercise, G = gift
                    if ad_code == "A" or code == "P":
                        total_acquired += shares
                        total_value += value
                    elif ad_code == "D" or code == "S":
                        total_disposed += shares
                        total_value += value

            # Build summary
            parts = []
            if owner_name:
                parts.append(owner_name)
            if total_acquired > 0 and total_disposed == 0:
                parts.append(f"BOUGHT {total_acquired:,.0f} shares")
                if total_value > 0:
                    parts.append(f"(${total_value:,.0f})")
                sentiment = 0.4  # Insider buying is bullish
            elif total_disposed > 0 and total_acquired == 0:
                parts.append(f"SOLD {total_disposed:,.0f} shares")
                if total_value > 0:
                    parts.append(f"(${total_value:,.0f})")
                sentiment = -0.1  # Insider selling is mildly negative
            elif total_acquired > 0 and total_disposed > 0:
                parts.append(f"acquired {total_acquired:,.0f}, disposed {total_disposed:,.0f} shares")
                sentiment = 0.1 if total_acquired > total_disposed else -0.1
            else:
                # Likely a grant/award/option exercise
                parts.append("option/grant transaction")
                sentiment = 0.0

            return {
                "summary": " ".join(parts) if parts else "insider transaction",
                "sentiment": sentiment,
            }
        except Exception:
            return None

    def _fetch_filings_rss(
        self, cik: str, symbol: str, form_type: str
    ) -> list[NewsItem]:
        """Fallback: use EDGAR RSS feed for recent filings."""
        items: list[NewsItem] = []
        try:
            url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&CIK={cik}&type={form_type}"
                f"&dateb=&owner=include&count=5&search_text=&action=getcompany"
                f"&output=atom"
            )
            response = self._http.get(url)
            if response.status_code != 200:
                return items

            root = ET.fromstring(response.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall("atom:entry", ns)[:3]:
                title = entry.findtext("atom:title", "", ns)
                updated = entry.findtext("atom:updated", "", ns)
                link_elem = entry.find("atom:link", ns)
                link = link_elem.get("href", "") if link_elem is not None else ""
                summary = entry.findtext("atom:summary", "", ns)

                sentiment = self._filing_sentiment(form_type, title + " " + summary)

                items.append(NewsItem(
                    title=f"SEC {form_type}: {symbol} — {title}",
                    source="sec_edgar",
                    published=updated,
                    symbols=[symbol],
                    sentiment=sentiment,
                    category="insider" if form_type == "4" else "filing",
                    url=link,
                    summary=summary[:200],
                    metadata={"form_type": form_type, "cik": cik},
                ))
        except Exception:
            pass

        return items

    def _filing_sentiment(self, form_type: str, text: str = "") -> float:
        """Estimate sentiment from filing type and content.

        8-K can be anything. Form 4 insider buys are bullish, sells neutral-ish.
        13D/13G (activist) are generally bullish.
        """
        text_lower = text.lower()

        if form_type == "4":
            if "purchase" in text_lower or "acquisition" in text_lower:
                return 0.4
            if "sale" in text_lower or "disposition" in text_lower:
                return -0.1  # Insiders sell for many reasons — mild negative
            return 0.0

        if form_type in ("13D", "13G", "SC 13D", "SC 13G"):
            return 0.3  # Activist positions are usually bullish catalysts

        if form_type == "8-K":
            # Try to detect from keywords
            if any(w in text_lower for w in ["acquisition", "merger", "agreement"]):
                return 0.3
            if any(w in text_lower for w in ["default", "delisting", "bankruptcy"]):
                return -0.6
            return 0.0

        return 0.0


# ══════════════════════════════════════════════════════════════
# 5. FRED Provider (macro context, not per-stock news)
# ══════════════════════════════════════════════════════════════

# Key FRED series for market regime assessment
FRED_SERIES = {
    "VIXCLS": "VIX (CBOE Volatility Index)",
    "DGS10": "10-Year Treasury Yield",
    "DFF": "Federal Funds Effective Rate",
    "T10Y2Y": "10Y-2Y Treasury Spread (inversion signal)",
    "BAMLH0A0HYM2": "High-Yield Bond Spread (credit stress)",
}


class FREDProvider:
    """Federal Reserve Economic Data — macro regime context.

    Not a news provider per se, but provides authoritative macro data
    that flows into market_context for regime assessment.

    Free API key required: https://fred.stlouisfed.org/docs/api/api_key.html
    """

    name = "fred"
    _BASE = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._http = httpx.Client(timeout=15)

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        """Not used for per-stock news. Use fetch_macro_context() instead."""
        return []

    def fetch_macro_context(self) -> dict:
        """Fetch latest values for key macro indicators.

        Returns a dict ready to merge into market_context.
        """
        if not self._api_key:
            return {}

        context = {}
        for series_id, description in FRED_SERIES.items():
            try:
                value = self._fetch_latest(series_id)
                if value is not None:
                    context[series_id] = {
                        "value": value,
                        "description": description,
                    }
            except Exception:
                continue

        # Derive regime signals from FRED data
        context["regime_signals"] = self._derive_regime_signals(context)
        return context

    def _fetch_latest(self, series_id: str) -> float | None:
        """Fetch the most recent observation for a FRED series."""
        try:
            params = {
                "series_id": series_id,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            }
            response = self._http.get(self._BASE, params=params)
            if response.status_code != 200:
                return None

            data = response.json()
            observations = data.get("observations", [])
            if not observations:
                return None

            value_str = observations[0].get("value", "")
            if value_str == "." or not value_str:
                return None

            return round(float(value_str), 4)
        except Exception:
            return None

    def _derive_regime_signals(self, context: dict) -> dict:
        """Interpret FRED data into actionable regime signals."""
        signals = {}

        # VIX interpretation
        vix_data = context.get("VIXCLS")
        if vix_data:
            vix = vix_data["value"]
            signals["volatility"] = {
                "value": vix,
                "level": (
                    "low" if vix < 15 else
                    "normal" if vix < 20 else
                    "elevated" if vix < 25 else
                    "high" if vix < 35 else
                    "extreme"
                ),
                "action": (
                    "Full position sizing" if vix < 20 else
                    "Reduce position sizes 25%" if vix < 25 else
                    "Half position sizes, tighter stops" if vix < 35 else
                    "Defensive only, avoid new longs"
                ),
            }

        # Yield curve interpretation (T10Y2Y)
        spread_data = context.get("T10Y2Y")
        if spread_data:
            spread = spread_data["value"]
            signals["yield_curve"] = {
                "value": spread,
                "status": (
                    "inverted" if spread < 0 else
                    "flat" if spread < 0.25 else
                    "normal" if spread < 1.5 else
                    "steep"
                ),
                "implication": (
                    "Recession risk elevated — favor defensive sectors"
                    if spread < 0 else
                    "Growth slowing — mixed signals"
                    if spread < 0.25 else
                    "Normal growth expected"
                ),
            }

        # Credit stress (high-yield spread)
        hy_data = context.get("BAMLH0A0HYM2")
        if hy_data:
            hy_spread = hy_data["value"]
            signals["credit_stress"] = {
                "value": hy_spread,
                "level": (
                    "calm" if hy_spread < 3.5 else
                    "normal" if hy_spread < 5.0 else
                    "stressed" if hy_spread < 7.0 else
                    "crisis"
                ),
                "action": (
                    "Risk-on environment" if hy_spread < 3.5 else
                    "Normal credit conditions" if hy_spread < 5.0 else
                    "Reduce exposure, favor quality" if hy_spread < 7.0 else
                    "Risk-off: cash and treasuries"
                ),
            }

        return signals


# ══════════════════════════════════════════════════════════════
# 6. Finnhub Provider
# ══════════════════════════════════════════════════════════════

class FinnhubProvider:
    """Finnhub.io — company news, social sentiment, insider transactions,
    analyst recommendation trends.

    Free tier: 60 calls/minute, no daily cap.
    API key: free signup at https://finnhub.io/
    """

    name = "finnhub"
    _BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._http = httpx.Client(timeout=15, follow_redirects=True)

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        """Fetch company news for given symbols.

        Deduplicates by headline to avoid overlap with yfinance (both
        source from Yahoo). Only keeps articles where the symbol appears
        in Finnhub's 'related' field to ensure relevance.
        """
        if not self._api_key:
            return []

        items: list[NewsItem] = []
        seen_titles: set[str] = set()
        today = _today()
        week_ago = _days_ago(3)  # 3 days, not 7 — recency matters more

        for symbol in symbols:
            try:
                params = {
                    "symbol": symbol,
                    "from": week_ago,
                    "to": today,
                    "token": self._api_key,
                }
                response = self._http.get(f"{self._BASE}/company-news", params=params)
                if response.status_code != 200:
                    continue

                news = response.json()
                if not isinstance(news, list):
                    continue

                for article in news[:10]:
                    title = article.get("headline", "")
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    # Skip articles where the symbol isn't in the 'related' field
                    related = article.get("related", "")
                    if related and symbol not in related:
                        continue

                    published = ""
                    ts = article.get("datetime")
                    if ts:
                        published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        )

                    items.append(NewsItem(
                        title=title,
                        source="finnhub",
                        published=published,
                        symbols=[symbol],
                        sentiment=score_headline(title),
                        category="headline",
                        url=article.get("url", ""),
                        summary=article.get("summary", "")[:500],
                        publisher=article.get("source", ""),
                        metadata={"finnhub_id": article.get("id")},
                    ))
            except Exception:
                continue

        return items

    def fetch_key_metrics(self, symbol: str) -> dict | None:
        """Fetch fundamental metrics — PE, margins, growth, beta, 52-week range.

        This is FREE data that adds critical context for stock narratives.
        """
        if not self._api_key:
            return None

        try:
            params = {"symbol": symbol, "metric": "all", "token": self._api_key}
            response = self._http.get(f"{self._BASE}/stock/metric", params=params)
            if response.status_code != 200:
                return None

            data = response.json()
            metric = data.get("metric", {})
            if not metric:
                return None

            return {
                "pe_ttm": metric.get("peTTM"),
                "eps_ttm": metric.get("epsInclExtraItemsTTM"),
                "revenue_growth_yoy": metric.get("revenueGrowthTTMYoy"),
                "eps_growth_yoy": metric.get("epsGrowthTTMYoy"),
                "gross_margin": metric.get("grossMarginTTM"),
                "net_margin": metric.get("netMarginTTM"),
                "roe": metric.get("roeTTM"),
                "beta": metric.get("beta"),
                "52w_high": metric.get("52WeekHigh"),
                "52w_low": metric.get("52WeekLow"),
                "52w_high_date": metric.get("52WeekHighDate"),
                "52w_low_date": metric.get("52WeekLowDate"),
                "market_cap_m": metric.get("marketCapitalization"),
                "avg_volume_10d": metric.get("10DayAverageTradingVolume"),
                "current_ratio": metric.get("currentRatioQuarterly"),
                "dividend_yield": metric.get("dividendYieldIndicatedAnnual"),
            }
        except Exception:
            return None

    def fetch_quote(self, symbol: str) -> dict | None:
        """Fetch current quote — price, change, high, low, open."""
        if not self._api_key:
            return None

        try:
            params = {"symbol": symbol, "token": self._api_key}
            response = self._http.get(f"{self._BASE}/quote", params=params)
            if response.status_code != 200:
                return None

            q = response.json()
            if not q or q.get("c", 0) == 0:
                return None

            return {
                "price": q.get("c"),
                "change": q.get("d"),
                "change_pct": q.get("dp"),
                "high": q.get("h"),
                "low": q.get("l"),
                "open": q.get("o"),
                "prev_close": q.get("pc"),
            }
        except Exception:
            return None

    def fetch_peers(self, symbol: str) -> list[str]:
        """Fetch peer companies for a symbol."""
        if not self._api_key:
            return []

        try:
            params = {"symbol": symbol, "token": self._api_key}
            response = self._http.get(f"{self._BASE}/stock/peers", params=params)
            if response.status_code != 200:
                return []

            peers = response.json()
            # Remove self from peers list
            return [p for p in peers if p != symbol] if isinstance(peers, list) else []
        except Exception:
            return []

    def fetch_social_sentiment(self, symbol: str) -> dict | None:
        """Fetch social media sentiment (Reddit, Twitter) for a stock.

        Returns aggregated sentiment data or None.
        """
        if not self._api_key:
            return None

        try:
            params = {"symbol": symbol, "token": self._api_key}
            response = self._http.get(
                f"{self._BASE}/stock/social-sentiment", params=params
            )
            if response.status_code != 200:
                return None

            data = response.json()
            reddit = data.get("reddit", [])
            twitter = data.get("twitter", [])

            reddit_score = 0.0
            reddit_mentions = 0
            for entry in reddit[-7:]:  # Last 7 data points
                reddit_score += entry.get("score", 0)
                reddit_mentions += entry.get("mention", 0)

            twitter_score = 0.0
            twitter_mentions = 0
            for entry in twitter[-7:]:
                twitter_score += entry.get("score", 0)
                twitter_mentions += entry.get("mention", 0)

            total_mentions = reddit_mentions + twitter_mentions
            if total_mentions == 0:
                return None

            avg_score = (reddit_score + twitter_score) / max(
                len(reddit[-7:]) + len(twitter[-7:]), 1
            )

            return {
                "reddit_mentions": reddit_mentions,
                "twitter_mentions": twitter_mentions,
                "total_mentions": total_mentions,
                "avg_score": round(avg_score, 4),
                "sentiment": (
                    "bullish" if avg_score > 0.1 else
                    "bearish" if avg_score < -0.1 else
                    "neutral"
                ),
            }
        except Exception:
            return None

    def fetch_insider_transactions(self, symbol: str) -> list[NewsItem]:
        """Fetch insider transactions from Finnhub."""
        if not self._api_key:
            return []

        items: list[NewsItem] = []
        try:
            params = {"symbol": symbol, "token": self._api_key}
            response = self._http.get(
                f"{self._BASE}/stock/insider-transactions", params=params
            )
            if response.status_code != 200:
                return items

            data = response.json().get("data", [])
            for tx in data[:5]:
                name = tx.get("name", "Unknown")
                shares = tx.get("share", 0)
                change = tx.get("change", 0)
                tx_type = tx.get("transactionType", "")
                filing_date = tx.get("filingDate", "")

                # Skip old transactions
                if filing_date and filing_date < _days_ago(30):
                    continue

                is_buy = change > 0 or "buy" in tx_type.lower() or "purchase" in tx_type.lower()
                is_sell = change < 0 or "sale" in tx_type.lower() or "sell" in tx_type.lower()

                if is_buy:
                    action = "BOUGHT"
                    sentiment = 0.3
                elif is_sell:
                    action = "SOLD"
                    sentiment = -0.1
                else:
                    action = tx_type or "transacted"
                    sentiment = 0.0

                items.append(NewsItem(
                    title=f"Insider: {name} {action} {abs(shares):,.0f} shares of {symbol}",
                    source="finnhub",
                    published=filing_date,
                    symbols=[symbol],
                    sentiment=sentiment,
                    category="insider",
                    metadata={
                        "insider_name": name,
                        "shares": shares,
                        "change": change,
                        "transaction_type": tx_type,
                    },
                ))
        except Exception:
            pass

        return items

    def fetch_recommendation_trends(self, symbol: str) -> dict | None:
        """Fetch analyst recommendation trends over time."""
        if not self._api_key:
            return None

        try:
            params = {"symbol": symbol, "token": self._api_key}
            response = self._http.get(
                f"{self._BASE}/stock/recommendation", params=params
            )
            if response.status_code != 200:
                return None

            data = response.json()
            if not data:
                return None

            latest = data[0]
            buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
            hold = latest.get("hold", 0)
            sell = latest.get("sell", 0) + latest.get("strongSell", 0)
            total = buy + hold + sell
            if total == 0:
                return None

            score = (buy - sell) / total

            # Check trend vs previous period
            trend = "stable"
            if len(data) >= 2:
                prev = data[1]
                prev_buy = prev.get("buy", 0) + prev.get("strongBuy", 0)
                prev_sell = prev.get("sell", 0) + prev.get("strongSell", 0)
                prev_total = prev_buy + prev.get("hold", 0) + prev_sell
                if prev_total > 0:
                    prev_score = (prev_buy - prev_sell) / prev_total
                    if score > prev_score + 0.1:
                        trend = "improving"
                    elif score < prev_score - 0.1:
                        trend = "deteriorating"

            return {
                "period": latest.get("period", ""),
                "strong_buy": latest.get("strongBuy", 0),
                "buy": latest.get("buy", 0),
                "hold": hold,
                "sell": latest.get("sell", 0),
                "strong_sell": latest.get("strongSell", 0),
                "score": round(score, 2),
                "trend": trend,
            }
        except Exception:
            return None


# ══════════════════════════════════════════════════════════════
# 7. Alpha Vantage Provider
# ══════════════════════════════════════════════════════════════

class AlphaVantageProvider:
    """Alpha Vantage — NLP-scored news with per-ticker sentiment relevance.

    Free tier: 25 requests/day (use sparingly, morning research only).
    API key: free signup at https://www.alphavantage.co/support/#api-key

    The NEWS_SENTIMENT endpoint returns:
    - Headlines with NLP sentiment scores
    - Per-ticker relevance scores (0-1)
    - Per-ticker sentiment scores and labels
    """

    name = "alpha_vantage"
    _BASE = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._http = httpx.Client(timeout=20, follow_redirects=True)

    def is_available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, symbols: list[str], **kwargs) -> list[NewsItem]:
        """Fetch NLP-scored news per symbol.

        Queries each symbol individually (not batched) because AV's API
        returns articles that mention ALL queried tickers when batched,
        which yields almost nothing. Per-symbol queries return 50 articles
        each with per-ticker relevance scores.

        Budget: 1 call per symbol. With 25/day limit, supports ~20 symbols
        plus a few broad queries.
        """
        if not self._api_key:
            return []

        items: list[NewsItem] = []
        seen_titles: set[str] = set()

        for symbol in symbols:
            batch_items = self._fetch_batch([symbol])
            for item in batch_items:
                if item.title not in seen_titles:
                    seen_titles.add(item.title)
                    items.append(item)

        return items

    def fetch_broad(self, topics: str = "financial_markets") -> list[NewsItem]:
        """Fetch broad market news with NLP sentiment (1 API call).

        Topics: financial_markets, economy_fiscal, economy_monetary,
                economy_macro, energy_transportation, finance, etc.
        """
        if not self._api_key:
            return []
        return self._fetch_batch([], topics=topics)

    def _fetch_batch(
        self,
        symbols: list[str],
        topics: str = "",
    ) -> list[NewsItem]:
        items: list[NewsItem] = []
        try:
            params: dict = {
                "function": "NEWS_SENTIMENT",
                "apikey": self._api_key,
                "limit": 50,  # Get more, filter by relevance
                "sort": "RELEVANCE",
            }
            if symbols:
                params["tickers"] = ",".join(symbols)
            if topics:
                params["topics"] = topics

            response = self._http.get(self._BASE, params=params)
            if response.status_code != 200:
                return items

            data = response.json()

            # Check for API error/rate limit messages
            if "Information" in data or "Note" in data or "Error Message" in data:
                return items

            feed = data.get("feed", [])
            for article in feed:
                title = article.get("title", "")
                if not title:
                    continue

                # Extract per-ticker sentiment (the unique value of Alpha Vantage)
                ticker_sentiments: dict[str, dict] = {}
                article_symbols: list[str] = []
                for ticker_data in article.get("ticker_sentiment", []):
                    ticker = ticker_data.get("ticker", "")
                    if not ticker:
                        continue
                    article_symbols.append(ticker)
                    relevance = float(ticker_data.get("relevance_score", 0))
                    ticker_sent = float(
                        ticker_data.get("ticker_sentiment_score", 0)
                    )
                    ticker_sentiments[ticker] = {
                        "relevance": round(relevance, 4),
                        "sentiment_score": round(ticker_sent, 4),
                        "sentiment_label": ticker_data.get(
                            "ticker_sentiment_label", ""
                        ),
                    }

                # Filter: only keep articles with high relevance to our symbols
                if symbols:
                    max_relevance = max(
                        (ticker_sentiments.get(s, {}).get("relevance", 0)
                         for s in symbols),
                        default=0,
                    )
                    if max_relevance < 0.5:
                        continue  # Skip low-relevance articles

                # Overall article sentiment
                overall_sentiment = float(
                    article.get("overall_sentiment_score", 0)
                )

                # Use per-ticker sentiment for targeted symbols (more precise)
                sentiment_score = overall_sentiment
                if symbols and ticker_sentiments:
                    relevant_scores = [
                        ts["sentiment_score"]
                        for sym, ts in ticker_sentiments.items()
                        if sym in symbols and ts["relevance"] > 0.5
                    ]
                    if relevant_scores:
                        sentiment_score = sum(relevant_scores) / len(
                            relevant_scores
                        )

                # Clamp to [-1, 1]
                sentiment_score = max(-1.0, min(1.0, round(sentiment_score, 3)))

                # Use the symbols we were looking for if they appear
                final_symbols = (
                    [s for s in symbols if s in article_symbols]
                    if symbols
                    else article_symbols
                )

                items.append(NewsItem(
                    title=title,
                    source="alpha_vantage",
                    published=article.get("time_published", ""),
                    symbols=final_symbols,
                    sentiment=sentiment_score,
                    category="headline",
                    url=article.get("url", ""),
                    summary=article.get("summary", "")[:600],  # Keep longer summaries — AV has the best text
                    publisher=article.get("source", ""),
                    metadata={
                        "overall_sentiment": overall_sentiment,
                        "overall_label": article.get(
                            "overall_sentiment_label", ""
                        ),
                        "ticker_sentiments": ticker_sentiments,
                        "topics": [
                            t.get("topic", "")
                            for t in article.get("topics", [])
                        ],
                    },
                ))
        except Exception:
            pass

        # Return top items by relevance (already sorted by API)
        return items[:10]


# ══════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════

def _parse_yfinance_news_item(item: dict) -> dict:
    """Support both old and current yfinance news payload shapes."""
    content = item.get("content", {}) if isinstance(item, dict) else {}
    provider = content.get("provider", {}) if isinstance(content, dict) else {}

    title = item.get("title") or content.get("title") or ""
    publisher = item.get("publisher") or provider.get("displayName") or ""
    published = (
        item.get("providerPublishTime")
        or item.get("pubDate")
        or content.get("pubDate")
        or content.get("displayTime")
        or ""
    )
    summary = (
        item.get("summary")
        or item.get("description")
        or content.get("summary")
        or content.get("description")
        or ""
    )
    item_type = item.get("type") or content.get("contentType") or ""
    canonical_url = content.get("canonicalUrl") if isinstance(content, dict) else {}
    clickthrough = content.get("clickThroughUrl") if isinstance(content, dict) else {}
    url = (
        item.get("link")
        or item.get("url")
        or (canonical_url.get("url") if isinstance(canonical_url, dict) else canonical_url)
        or (clickthrough.get("url") if isinstance(clickthrough, dict) else clickthrough)
        or ""
    )

    return {
        "title": title,
        "publisher": publisher,
        "published": published,
        "summary": summary,
        "type": item_type,
        "url": url,
    }


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    from datetime import timedelta
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")
