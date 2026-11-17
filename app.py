import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import html
import re

# 请把邮箱改成你自己的（SEC 要求）
HEADERS = {"User-Agent": "PE-Website aihuaxiawenhua@gmail.com"}

# 你的 Seeking Alpha 专属推广链接
SA_REFERRAL_URL = (
    "https://seekingalpha.com/subscriptions/refer-a-friend"
    "?source=refer_friend_link&user_referrer=91b69c96c70651cc37407aca"
)

st.set_page_config(page_title="美股估值看板", layout="wide")

st.markdown("""
    <style>
    .block-container {
        padding-top: 3.2rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.35rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }
    .placeholder-box {
        height: 255px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        color: #888888;
        background-color: rgba(128, 128, 128, 0.04);
        border: 1px dashed rgba(128, 128, 128, 0.3);
        border-radius: 8px;
        text-align: center;
    }
    /* Seeking Alpha 分析文章滚动列表样式 */
    .sa-scroll-box {
        height: 255px;
        overflow-y: auto;
        padding-right: 6px;
    }
    .sa-item {
        padding: 9px 4px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.16);
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
    }
    .sa-item:last-child {
        border-bottom: none;
    }
    .sa-item-main {
        flex: 1;
        min-width: 0;
    }
    .sa-item-main a {
        text-decoration: none;
        font-size: 0.88rem;
        font-weight: 600;
        line-height: 1.4;
        display: block;
    }
    .sa-item-main a:hover {
        text-decoration: underline;
    }
    .sa-meta {
        font-size: 0.75rem;
        color: #888888;
        margin-top: 4px;
    }
    /* 复刻 Seeking Alpha 官网经典评级胶囊样式 */
    .sa-rating {
        flex-shrink: 0;
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 700;
        line-height: 1.4;
        text-align: center;
        min-width: 58px;
        margin-top: 1px;
        letter-spacing: 0.3px;
    }
    .sa-strong-buy {
        background-color: #12733b;
        color: #ffffff;
    }
    .sa-buy {
        background-color: #1ca45c;
        color: #ffffff;
    }
    .sa-hold {
        background-color: #f5b400;
        color: #1f1f1f;
    }
    .sa-sell {
        background-color: #e03e2d;
        color: #ffffff;
    }
    .sa-strong-sell {
        background-color: #a81818;
        color: #ffffff;
    }
    </style>
""", unsafe_allow_html=True)

head_col1, head_col2, head_col3 = st.columns([2.5, 1, 1], vertical_alignment="center")
with head_col1:
    st.markdown("### 📊 美股核心数据看板")
with head_col2:
    ticker = st.text_input(
        "股票代码", "AAPL",
        placeholder="输入代码如 AAPL、SPY、QQQ",
        label_visibility="collapsed"
    ).upper().strip()
with head_col3:
    years = st.selectbox(
        "时间范围", [1, 3, 5, 10], index=3,
        format_func=lambda x: f"过去 {x} 年",
        label_visibility="collapsed"
    )


def to_ns(s):
    dt = pd.to_datetime(s)
    if isinstance(dt, pd.Timestamp):
        return dt.as_unit("ns")
    return dt.astype("datetime64[ns]")


def format_pub_date(raw_date):
    if not raw_date:
        return ""
    try:
        dt = parsedate_to_datetime(raw_date)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            dt = pd.to_datetime(raw_date)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(raw_date)[:16]


# Seeking Alpha 官方评级映射表 -> (中文文案, CSS类名)
RATING_MAP = {
    "strong_buy": ("强烈买入", "sa-strong-buy"),
    "very_bullish": ("强烈买入", "sa-strong-buy"),
    "strong buy": ("强烈买入", "sa-strong-buy"),
    "buy": ("买入", "sa-buy"),
    "bullish": ("买入", "sa-buy"),
    "hold": ("持有", "sa-hold"),
    "neutral": ("持有", "sa-hold"),
    "sell": ("卖出", "sa-sell"),
    "bearish": ("卖出", "sa-sell"),
    "strong_sell": ("强烈卖出", "sa-strong-sell"),
    "very_bearish": ("强烈卖出", "sa-strong-sell"),
    "strong sell": ("强烈卖出", "sa-strong-sell"),
}


def infer_rating_from_title(title_en):
    """当备用 RSS 通道未携带结构化评级字段时，根据分析标题语义精准推断评级"""
    t = title_en.lower()
    if re.search(r"\bstrong\s+buy\b|\bscreaming\s+buy\b|\btable[- ]pounding\s+buy\b|\bgenerational\s+buy\b", t):
        return "strong_buy"
    if re.search(r"\bstrong\s+sell\b", t):
        return "strong_sell"
    if re.search(r"\bdowngrad\w*\s+to\s+sell\b|\brating\s+cut\s+to\s+sell\b|\bsell\s+now\b|\btime\s+to\s+sell\b|\bavoid\b|\bovervalued\b|\bbubble\b|\bbearish\b", t):
        return "sell"
    if re.search(r"\bdowngrad\w*\s+to\s+hold\b|\bhold\s+for\s+now\b|\bwait\s+for\s+a?\s*pullback\b|\bfairly\s+valued\b|\bpriced\s+in\b|\bsidelines\b|\bcautious\b|\bhold\b", t):
        return "hold"
    if re.search(r"\bupgrad\w*\s+to\s+buy\b|\bbuy\s+the\s+dip\b|\bundervalued\b|\bbullish\b|\bworth\s+buying\b|\bstill\s+a\s+buy\b|\breiterat\w+\s+buy\b|\bbuy\b", t):
        return "buy"
    return "hold"


def translate_titles_to_zh(titles):
    """使用免费 Google Translate 接口批量将英文标题翻译为简体中文"""
    if not titles:
        return titles
    sep = "\n ||| \n"
    joined = sep.join(titles)
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "en",
                "tl": "zh-CN",
                "dt": "t",
                "q": joined,
            },
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            translated_full = "".join(seg[0] for seg in data[0] if seg and seg[0])
            parts = [p.strip() for p in translated_full.split("|||")]
            if len(parts) == len(titles):
                return parts
    except Exception:
        pass

    res = []
    for t in titles:
        zh = t
        try:
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": t},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                zh = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip() or t
        except Exception:
            pass
        res.append(zh)
    return res


@st.cache_data(ttl=1800)
def load_seeking_alpha_feed(symbol):
    """
    仅获取 Seeking Alpha 股票深度分析文章（剔除快讯），并读取分析师评级与作者信息：
    通道 1：Seeking Alpha 官网 v3 Articles JSON API（含官方 sentiments 精确评级）
    通道 2：Seeking Alpha 官方 XML 分析流（严格过滤仅保留 /article/ 分析文章）
    通道 3：Google News 定向检索 seekingalpha.com/article 分析文章兜底
    """
    json_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://seekingalpha.com/symbol/{symbol.lower()}/analysis",
    }

    articles = []

    # 通道 1：Seeking Alpha v3 Articles API（纯分析文章 + 原生分析师评级）
    v3_url = f"https://seekingalpha.com/api/v3/symbols/{symbol.lower()}/articles?page[size]=15"
    try:
        r = requests.get(v3_url, headers=json_headers, timeout=10)
        if r.status_code == 200:
            payload = r.json()
            data_list = payload.get("data") or []
            included = payload.get("included") or []

            # 建立 included 字典（提取作者姓名、目标股票对应的官方评级类型）
            inc_map = {(item.get("type"), str(item.get("id"))): item for item in included}
            tag_id_for_sym = None
            for item in included:
                if item.get("type") == "tag":
                    slug = (item.get("attributes", {}).get("slug") or "").upper()
                    name = (item.get("attributes", {}).get("name") or "").upper()
                    if slug == symbol or name == symbol:
                        tag_id_for_sym = str(item.get("id"))
                        break

            # 建立 sentiment_id -> rating_key 映射（如 strong_buy / buy / hold / sell / strong_sell）
            sent_rating_map = {}
            for item in included:
                if item.get("type") == "sentiment":
                    sid = str(item.get("id"))
                    attrs = item.get("attributes") or {}
                    rels = item.get("relationships") or {}
                    # 检查是否对应当前查询的股票代码（若存在多标的）
                    sent_tag_id = str((rels.get("tag", {}).get("data") or {}).get("id") or "")
                    r_type = str(attrs.get("type") or attrs.get("sentimentId") or "").lower()
                    # 数字枚举兼容（SA 部分版本返回 1:strong_buy, 2:buy, 3:hold, 4:sell, 5:strong_sell）
                    num_map = {"1": "strong_buy", "2": "buy", "3": "hold", "4": "sell", "5": "strong_sell"}
                    r_key = num_map.get(r_type, r_type)
                    if r_key in RATING_MAP:
                        sent_rating_map[sid] = (r_key, sent_tag_id)

            for art in data_list:
                if art.get("type") != "article":
                    continue
                attrs = art.get("attributes") or {}
                title = (attrs.get("title") or "").strip()
                if not title:
                    continue
                pub = format_pub_date(attrs.get("publishOn") or "")

                # 解析作者名
                rels = art.get("relationships") or {}
                author_id = str((rels.get("author", {}).get("data") or {}).get("id") or "")
                author_obj = inc_map.get(("author", author_id), {})
                author_name = (author_obj.get("attributes", {}).get("nick") or "Seeking Alpha Analyst").strip()

                # 解析该文章对当前股票的官方评级
                rating_key = None
                sent_list = (rels.get("sentiments", {}).get("data")) or []
                if isinstance(sent_list, dict):
                    sent_list = [sent_list]
                for s_ref in sent_list:
                    sid = str(s_ref.get("id") or "")
                    if sid in sent_rating_map:
                        rk, st_id = sent_rating_map[sid]
                        if not tag_id_for_sym or not st_id or st_id == tag_id_for_sym:
                            rating_key = rk
                            break
                        if rating_key is None:
                            rating_key = rk

                if not rating_key:
                    rating_key = infer_rating_from_title(title)

                articles.append({
                    "title_en": title,
                    "date": pub,
                    "author": author_name,
                    "rating_key": rating_key,
                })
    except Exception:
        pass

    # 通道 2：Seeking Alpha 官方 XML Feed（严格只取 /article/ 分析类，彻底丢弃快讯）
    if not articles:
        xml_headers = {
            "User-Agent": json_headers["User-Agent"],
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }
        sa_url = f"https://seekingalpha.com/api/sa/combined/{symbol}.xml"
        try:
            r = requests.get(sa_url, headers=xml_headers, timeout=12)
            if r.status_code == 200 and r.content:
                root = ET.fromstring(r.content)
                ns = {"sa": "https://seekingalpha.com/api/1.0"}
                for item in root.findall("./channel/item"):
                    orig_link = (item.findtext("link") or "").strip()
                    # 只保留分析文章（/article/），跳过一切快讯（/news/ 等）
                    if "/article/" not in orig_link:
                        continue
                    title = (item.findtext("title") or "").strip()
                    pub = format_pub_date(item.findtext("pubDate") or "")
                    author = (item.findtext("sa:author_name", namespaces=ns) or "").strip()
                    if title:
                        articles.append({
                            "title_en": title,
                            "date": pub,
                            "author": author or "Seeking Alpha Analyst",
                            "rating_key": infer_rating_from_title(title),
                        })
                    if len(articles) >= 15:
                        break
        except Exception:
            pass

    # 通道 3（终极防爬兜底）：Google News RSS 限定 site:seekingalpha.com/article（纯分析文章）
    if not articles:
        gn_url = (
            f"https://news.google.com/rss/search?"
            f"q=site:seekingalpha.com/article+{symbol}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            r = requests.get(gn_url, headers={"User-Agent": json_headers["User-Agent"]}, timeout=12)
            if r.status_code == 200 and r.content:
                root = ET.fromstring(r.content)
                for item in root.findall("./channel/item")[:15]:
                    raw_title = (item.findtext("title") or "").strip()
                    clean_title = raw_title.rsplit(" - Seeking Alpha", 1)[0].strip()
                    pub = format_pub_date(item.findtext("pubDate") or "")
                    if clean_title:
                        articles.append({
                            "title_en": clean_title,
                            "date": pub,
                            "author": "Seeking Alpha Analyst",
                            "rating_key": infer_rating_from_title(clean_title),
                        })
        except Exception:
            pass

    # 批量翻译英文标题为简体中文，并挂载对应的评级样式
    if articles:
        zh_titles = translate_titles_to_zh([a["title_en"] for a in articles])
        for art, zh in zip(articles, zh_titles):
            art["title_zh"] = zh
            label, css_cls = RATING_MAP.get(art["rating_key"], ("持有", "sa-hold"))
            art["rating_label"] = label
            art["rating_cls"] = css_cls

    return articles


@st.cache_data(ttl=86400)
def get_cik_map():
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    return {item["ticker"].upper(): int(item["cik_str"]) for item in r.json().values()}


@st.cache_data(ttl=86400)
def get_sec_facts(symbol):
    cik_map = get_cik_map()
    cik = cik_map.get(symbol) or cik_map.get(symbol.replace(".", "-"))
    if cik is None:
        return None
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("facts", {}).get("us-gaap", {})


def build_ttm_eps(facts, splits_series):
    rows = None
    for concept in ["EarningsPerShareDiluted", "EarningsPerShareBasic"]:
        if concept in facts and "USD/shares" in facts[concept]["units"]:
            rows = facts[concept]["units"]["USD/shares"]
            break
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["start", "end", "filed", "val"])
    df = df[df["form"].isin(["10-Q", "10-K", "10-Q/A", "10-K/A"])].copy()
    if df.empty:
        return None

    df["start"] = to_ns(df["start"])
    df["end"] = to_ns(df["end"])
    df["filed"] = to_ns(df["filed"])
    df["val"] = df["val"].astype(float)
    df["dur"] = (df["end"] - df["start"]).dt.days

    first_filed = df.groupby(["start", "end"])["filed"].min().rename("first_filed")
    latest = (df.sort_values("filed")
                .groupby(["start", "end"], as_index=False)
                .last()
                .merge(first_filed, on=["start", "end"]))

    def adj_split(row):
        f = 1.0
        for sd, ratio in splits_series.items():
            if sd > row["filed"]:
                f *= float(ratio)
        return row["val"] / f

    latest["val_adj"] = latest.apply(adj_split, axis=1)

    q_direct = latest[latest["dur"].between(65, 115)].copy()
    q_map = {}
    for _, r in q_direct.iterrows():
        q_map[r["end"]] = {
            "start": r["start"],
            "end": r["end"],
            "val": r["val_adj"],
            "filed": r["first_filed"],
        }

    cum_df = latest[latest["dur"].between(165, 385)].sort_values("dur")
    for _, yr in cum_df.iterrows():
        if yr["end"] in q_map:
            continue
        inside = [
            v for v in q_map.values()
            if v["start"] >= yr["start"] - pd.Timedelta(days=7)
            and v["end"] < yr["end"] - pd.Timedelta(days=30)
        ]
        inside_days = sum((v["end"] - v["start"]).days for v in inside)
        rem_days = yr["dur"] - inside_days
        if 65 <= rem_days <= 120:
            q_val = yr["val_adj"] - sum(v["val"] for v in inside)
            prev_end = max(v["end"] for v in inside) if inside else yr["start"]
            q_map[yr["end"]] = {
                "start": prev_end,
                "end": yr["end"],
                "val": q_val,
                "filed": yr["first_filed"],
            }

    if not q_map:
        return None

    qdf = pd.DataFrame(list(q_map.values())).sort_values("end").reset_index(drop=True)

    cleaned = []
    for _, r in qdf.iterrows():
        if cleaned and (r["end"] - cleaned[-1]["end"]).days < 20:
            cleaned[-1] = r.to_dict()
        else:
            cleaned.append(r.to_dict())
    qdf = pd.DataFrame(cleaned)
    qdf["start"] = to_ns(qdf["start"])
    qdf["end"] = to_ns(qdf["end"])
    qdf["filed"] = to_ns(qdf["filed"])

    ttm_rows = []
    for i in range(3, len(qdf)):
        w = qdf.iloc[i - 3:i + 1]
        span = (w["end"].iloc[-1] - w["end"].iloc[0]).days
        if 240 <= span <= 320:
            ttm_rows.append({
                "period_end": w["end"].iloc[-1],
                "filed": w["filed"].max(),
                "ttm": float(w["val"].sum()),
            })

    if not ttm_rows:
        return None

    ttm_df = (pd.DataFrame(ttm_rows)
              .sort_values(["filed", "period_end"])
              .drop_duplicates("filed", keep="last")
              .reset_index(drop=True))
    ttm_df["filed"] = to_ns(ttm_df["filed"])
    return ttm_df, qdf


@st.cache_data(ttl=86400)
def load_stock_pe(symbol, years):
    facts = get_sec_facts(symbol)
    if not facts:
        return None, None

    t = yf.Ticker(symbol)
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)
    fetch_start = start - pd.DateOffset(months=6)

    hist = t.history(start=fetch_start.strftime("%Y-%m-%d"), auto_adjust=False)
    if hist.empty:
        return None, None

    df = hist[["Close"]].reset_index()
    df.columns = ["date", "close"]
    d = pd.to_datetime(df["date"])
    if d.dt.tz is not None:
        d = d.dt.tz_localize(None)
    df["date"] = to_ns(d)
    df["close"] = df["close"].astype(float)

    sp = pd.Series(dtype=float)
    try:
        s = t.splits
        if s is not None and len(s) > 0:
            sp = s.copy()
            idx = pd.to_datetime(sp.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            sp.index = to_ns(idx)
    except Exception:
        pass

    res = build_ttm_eps(facts, sp)
    if res is None:
        return None, None
    ttm_df, qdf = res

    df = pd.merge_asof(
        df.sort_values("date").reset_index(drop=True),
        ttm_df[["filed", "ttm"]],
        left_on="date", right_on="filed", direction="backward",
    )
    df["pe"] = (df["close"] / df["ttm"]).where(df["ttm"] > 0)
    df = df[df["date"] >= start].reset_index(drop=True)
    return df, qdf


FALLBACK_HOLDINGS = {
    "SPY": [("AAPL", 0.07), ("MSFT", 0.065), ("NVDA", 0.06), ("AMZN", 0.038), ("META", 0.025), ("GOOGL", 0.04), ("BRK-B", 0.018), ("AVGO", 0.018), ("LLY", 0.015), ("JPM", 0.014)],
    "VOO": [("AAPL", 0.07), ("MSFT", 0.065), ("NVDA", 0.06), ("AMZN", 0.038), ("META", 0.025), ("GOOGL", 0.04), ("BRK-B", 0.018), ("AVGO", 0.018), ("LLY", 0.015), ("JPM", 0.014)],
    "QQQ": [("AAPL", 0.088), ("MSFT", 0.082), ("NVDA", 0.078), ("AMZN", 0.052), ("AVGO", 0.045), ("META", 0.045), ("TSLA", 0.035), ("GOOGL", 0.052), ("COST", 0.026), ("NFLX", 0.022)],
    "DIA": [("UNH", 0.08), ("GS", 0.075), ("MSFT", 0.062), ("HD", 0.058), ("CAT", 0.052), ("AMGN", 0.046), ("V", 0.044), ("CRM", 0.042), ("MCD", 0.042), ("AXP", 0.04)],
}


@st.cache_data(ttl=86400)
def load_etf_pe(symbol, years):
    t = yf.Ticker(symbol)
    info = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    official_pe = info.get("trailingPE")

    holdings = []
    try:
        fd = t.funds_data
        if fd is not None and fd.top_holdings is not None and not fd.top_holdings.empty:
            th = fd.top_holdings
            for h_sym, row in th.iterrows():
                w = float(row.get("Holding Percent", 0))
                if h_sym and w > 0:
                    holdings.append((str(h_sym).upper(), w))
    except Exception:
        pass

    if not holdings and symbol in FALLBACK_HOLDINGS:
        holdings = FALLBACK_HOLDINGS[symbol]

    if not holdings:
        return None, None

    ep_frames = []
    used_holdings = []
    for h_sym, weight in holdings[:10]:
        sub_df, _ = load_stock_pe(h_sym, years)
        if sub_df is not None and not sub_df.empty:
            sub = sub_df[["date", "close", "ttm"]].dropna().copy()
            if not sub.empty:
                sub["ep"] = sub["ttm"] / sub["close"]
                sub = sub.set_index("date")[["ep"]].rename(columns={"ep": h_sym})
                ep_frames.append((h_sym, weight, sub))
                used_holdings.append({"成分股": h_sym, "权重占比": f"{weight * 100:.2f}%"})

    if not ep_frames:
        return None, None

    merged = pd.concat([f[2] for f in ep_frames], axis=1).sort_index().ffill()
    weights = pd.Series({f[0]: f[1] for f in ep_frames})

    valid_mask = merged.notna()
    weighted_ep = merged.multiply(weights, axis=1).sum(axis=1)
    active_weight = valid_mask.multiply(weights, axis=1).sum(axis=1)

    basket_ep = (weighted_ep / active_weight).where(active_weight > 0)
    basket_pe = (1.0 / basket_ep).where(basket_ep > 0)

    res_df = pd.DataFrame({"date": basket_pe.index, "pe": basket_pe.values}).dropna()
    if res_df.empty:
        return None, None

    if official_pe and official_pe > 0:
        scale = float(official_pe) / res_df["pe"].iloc[-1]
        if 0.4 <= scale <= 2.5:
            res_df["pe"] = res_df["pe"] * scale

    meta = {
        "is_etf": True,
        "official_pe": official_pe,
        "holdings_df": pd.DataFrame(used_holdings),
    }
    return res_df.reset_index(drop=True), meta


def load_any_pe(symbol, years):
    df, qdf = load_stock_pe(symbol, years)
    if df is not None and not df["pe"].dropna().empty:
        return df, {"is_etf": False, "qdf": qdf}

    etf_df, etf_meta = load_etf_pe(symbol, years)
    if etf_df is not None and not etf_df["pe"].dropna().empty:
        return etf_df, etf_meta

    return None, None


# ==================== 2x2 四宫格主体布局 ====================
row1_left, row1_right = st.columns(2, gap="small")
row2_left, row2_right = st.columns(2, gap="small")

detail_meta = None

# 【左上角】：历史市盈率走势模块
with row1_left:
    with st.container(border=True):
        if ticker:
            with st.spinner(f"正在加载 {ticker} 估值数据..."):
                df, detail_meta = load_any_pe(ticker, years)

            is_etf = bool(detail_meta and detail_meta.get("is_etf"))
            tag = "ETF 重仓拟合" if is_etf else "PE-TTM"
            st.markdown(f"**📈 {ticker} 历史市盈率 ({tag})**")

            if df is None or df["pe"].dropna().empty:
                st.error("未找到有效 PE 数据，请检查代码（如 AAPL、SPY、QQQ）或确认邮箱已修改。")
            else:
                valid = df.dropna(subset=["pe"])
                median = valid["pe"].median()
                current_pe = valid["pe"].iloc[-1]
                percentile = (valid["pe"] < current_pe).mean() * 100

                m1, m2, m3 = st.columns(3)
                if pd.isna(df["pe"].iloc[-1]):
                    m1.metric("当前 PE", "亏损 (N/A)")
                else:
                    m1.metric("当前 PE", f"{current_pe:.1f}")
                m2.metric("历史中位数", f"{median:.1f}")
                m3.metric("历史分位", f"{percentile:.0f}%")

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df["date"],
                    y=df["pe"],
                    mode="lines",
                    name="PE",
                    connectgaps=False,
                ))
                fig.add_hline(y=median, line_dash="dash", annotation_text=f"中位 {median:.1f}")
                fig.update_layout(
                    height=195,
                    margin=dict(l=5, r=5, t=8, b=5),
                    yaxis_title="PE",
                    xaxis_title=None,
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# 【右上角】：Seeking Alpha 股票深度分析列表（纯分析 + SA 同款评级胶囊 + 中文标题 + 专属推广链接）
with row1_right:
    with st.container(border=True):
        safe_ref_url = html.escape(SA_REFERRAL_URL, quote=True)
        sa_head1, sa_head2 = st.columns([2.8, 1.2])
        with sa_head1:
            st.markdown(f"**📰 Seeking Alpha 最新分析 ({ticker})**")
        with sa_head2:
            st.markdown(
                f"<div style='text-align:right; font-size:0.8rem;'>"
                f"<a href='{safe_ref_url}' target='_blank' rel='noopener noreferrer' "
                f"style='text-decoration:none; color:#e66a00; font-weight:600;'>订阅优惠解锁 ↗</a></div>",
                unsafe_allow_html=True,
            )

        if ticker:
            with st.spinner("正在拉取 Seeking Alpha 股票分析与评级..."):
                sa_articles = load_seeking_alpha_feed(ticker)

            if not sa_articles:
                st.markdown(f"""
                    <div class="placeholder-box">
                        <div>📭 暂未获取到 {html.escape(ticker)} 的最新深度分析文章</div>
                        <div style="font-size: 0.8rem; margin-top: 6px;">
                            <a href="{safe_ref_url}" target="_blank" rel="noopener noreferrer">点击前往 Seeking Alpha 官网查看 ↗</a>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            else:
                items_html = []
                for art in sa_articles:
                    safe_title_zh = html.escape(art.get("title_zh") or art["title_en"])
                    safe_title_en = html.escape(art["title_en"], quote=True)
                    safe_author = html.escape(art["author"])
                    safe_date = html.escape(art["date"])
                    r_label = html.escape(art["rating_label"])
                    r_cls = html.escape(art["rating_cls"], quote=True)
                    items_html.append(
                        f'<div class="sa-item">'
                        f'<div class="sa-item-main">'
                        f'<a href="{safe_ref_url}" target="_blank" rel="noopener noreferrer" title="{safe_title_en}">{safe_title_zh}</a>'
                        f'<div class="sa-meta">{safe_author} &nbsp;·&nbsp; {safe_date}</div>'
                        f'</div>'
                        f'<span class="sa-rating {r_cls}">{r_label}</span>'
                        f'</div>'
                    )
                st.markdown(
                    f'<div class="sa-scroll-box">{"".join(items_html)}</div>',
                    unsafe_allow_html=True,
                )

# 【左下角】：预留功能位 2
with row2_left:
    with st.container(border=True):
        st.markdown("**🧩 预留模块 2（左下）**")
        st.markdown("""
            <div class="placeholder-box">
                <div>🚧 功能预留位</div>
                <div style="font-size: 0.85rem; margin-top: 6px;">例如：季度营收与净利润柱状图</div>
            </div>
        """, unsafe_allow_html=True)

# 【右下角】：预留功能位 3
with row2_right:
    with st.container(border=True):
        st.markdown("**🧩 预留模块 3（右下）**")
        st.markdown("""
            <div class="placeholder-box">
                <div>🚧 功能预留位</div>
                <div style="font-size: 0.85rem; margin-top: 6px;">例如：同行业多股票对比 / 自由现金流走势</div>
            </div>
        """, unsafe_allow_html=True)

# 底部折叠明细
if detail_meta is not None:
    if detail_meta.get("is_etf"):
        with st.expander(f"🔍 说明：{ticker} 为 ETF 基金，点击查看参与拟合的前十大核心成分股"):
            st.caption("注：ETF 无 SEC 10-Q/10-K 财报，曲线由核心重仓股历史加权盈利率(E/P)合成，并按基金最新整体 PE 校准。")
            st.dataframe(detail_meta["holdings_df"], height=180, use_container_width=True)
    elif detail_meta.get("qdf") is not None:
        with st.expander("🔍 展开核对底层单季 EPS 明细"):
            show_q = detail_meta["qdf"].sort_values("end", ascending=False).copy()
            show_q["end"] = show_q["end"].dt.strftime("%Y-%m-%d")
            show_q["filed"] = show_q["filed"].dt.strftime("%Y-%m-%d")
            show_q["val"] = show_q["val"].round(4)
            st.dataframe(
                show_q[["end", "filed", "val"]].rename(columns={
                    "end": "财报期末",
                    "filed": "首次披露日",
                    "val": "拆股调整后单季EPS($)",
                }),
                height=200,
                use_container_width=True,
            )

st.caption("数据来源：Yahoo Finance、SEC EDGAR、Seeking Alpha，仅供参考，不构成投资建议。")
