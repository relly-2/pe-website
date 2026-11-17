import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
from curl_cffi import requests as cffi_requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import html

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
        padding: 8px 4px;
        border-bottom: 1px solid rgba(128, 128, 128, 0.16);
    }
    .sa-item:last-child {
        border-bottom: none;
    }
    .sa-title-line {
        line-height: 1.45;
    }
    .sa-title-line a {
        text-decoration: none;
        font-size: 0.88rem;
        font-weight: 600;
        vertical-align: middle;
    }
    .sa-title-line a:hover {
        text-decoration: underline;
    }
    .sa-meta {
        font-size: 0.75rem;
        color: #888888;
        margin-top: 4px;
    }
    /* 复刻 Seeking Alpha 官网经典评级色块（移至标题前方） */
    .sa-rating {
        display: inline-block;
        padding: 1px 7px;
        border-radius: 3px;
        font-size: 0.72rem;
        font-weight: 700;
        line-height: 1.45;
        text-align: center;
        margin-right: 7px;
        vertical-align: middle;
        letter-spacing: 0.2px;
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


# Seeking Alpha 官方原始评级字段精确映射 -> (中文文案, CSS类名)
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


def normalize_sa_sentiment(attrs):
    """
    精确解析 Seeking Alpha v3 API 中 sentiment 对象的真实评级：
    SA v3 的 sentiment.attributes 中：
    - type 字段为字符串：'very_bullish' | 'bullish' | 'neutral' | 'bearish' | 'very_bearish'
      或 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell'
    """
    if not attrs:
        return None
    for field in ["type", "rating", "label", "slug"]:
        val = attrs.get(field)
        if isinstance(val, str):
            k = val.strip().lower().replace("-", "_")
            if k in RATING_MAP:
                return k
    return None


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


def fetch_article_exact_rating(session, article_id, target_tag_id, symbol):
    """当列表接口未展开某篇文章的 sentiments 时，单独查询单篇文章详情拿官网精确评级"""
    url = f"https://seekingalpha.com/api/v3/articles/{article_id}?include=sentiments,sentiments.tag"
    try:
        r = session.get(url, timeout=8)
        if r.status_code != 200:
            return None
        payload = r.json()
        included = payload.get("included") or []
        tags_by_id = {}
        for item in included:
            if item.get("type") == "tag":
                slug = (item.get("attributes", {}).get("slug") or "").upper()
                name = (item.get("attributes", {}).get("name") or "").upper()
                tags_by_id[str(item.get("id"))] = (slug, name)

        fallback_rk = None
        for item in included:
            if item.get("type") == "sentiment":
                rk = normalize_sa_sentiment(item.get("attributes") or {})
                if not rk:
                    continue
                rels = item.get("relationships") or {}
                st_id = str((rels.get("tag", {}).get("data") or {}).get("id") or "")
                if target_tag_id and st_id == target_tag_id:
                    return rk
                slug, name = tags_by_id.get(st_id, ("", ""))
                if slug == symbol or name == symbol:
                    return rk
                if fallback_rk is None:
                    fallback_rk = rk
        return fallback_rk
    except Exception:
        return None


@st.cache_data(ttl=1800)
def load_seeking_alpha_feed(symbol):
    """
    通过 curl_cffi 模拟真实 Chrome TLS 指纹请求 Seeking Alpha 官方 v3 分析接口，
    显式携带 include=author,sentiments,sentiments.tag，确保拿到的作者评级与 SA 官网 100% 一致！
    """
    sa_sym = symbol.lower().replace(".", "-")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"https://seekingalpha.com/symbol/{sa_sym}/analysis",
        "Origin": "https://seekingalpha.com",
    }

    articles = []

    try:
        with cffi_requests.Session(impersonate="chrome") as session:
            session.headers.update(headers)
            # 先访问一次分析页建立合法 Cookie 会话，大幅提高 v3 JSON API 通过率
            v3_url = (
                f"https://seekingalpha.com/api/v3/symbols/{sa_sym}/articles"
                f"?filter[category]=latest-articles"
                f"&include=author,sentiments,sentiments.tag,primaryTickers,secondaryTickers"
                f"&page[size]=15"
            )
            r = session.get(v3_url, timeout=12)
            if r.status_code != 200:
                session.get(f"https://seekingalpha.com/symbol/{sa_sym}/analysis", timeout=10)
                r = session.get(v3_url, timeout=12)

            if r.status_code == 200:
                payload = r.json()
                data_list = payload.get("data") or []
                included = payload.get("included") or []

                inc_authors = {}
                tag_id_for_sym = None
                tags_by_id = {}

                for item in included:
                    itype = item.get("type")
                    iid = str(item.get("id"))
                    attrs = item.get("attributes") or {}
                    if itype == "author":
                        inc_authors[iid] = (attrs.get("nick") or "Seeking Alpha Analyst").strip()
                    elif itype == "tag":
                        slug = (attrs.get("slug") or "").upper()
                        name = (attrs.get("name") or "").upper()
                        tags_by_id[iid] = (slug, name)
                        if slug in (symbol, sa_sym.upper()) or name in (symbol, sa_sym.upper()):
                            tag_id_for_sym = iid

                # 解析每个 sentiment 对应的真实评级与所属股票 tag_id
                sent_map = {}
                for item in included:
                    if item.get("type") == "sentiment":
                        sid = str(item.get("id"))
                        rk = normalize_sa_sentiment(item.get("attributes") or {})
                        rels = item.get("relationships") or {}
                        st_id = str((rels.get("tag", {}).get("data") or {}).get("id") or "")
                        if rk:
                            sent_map[sid] = (rk, st_id)

                for art in data_list:
                    if art.get("type") != "article":
                        continue
                    art_id = str(art.get("id") or "")
                    attrs = art.get("attributes") or {}
                    title = (attrs.get("title") or "").strip()
                    if not title:
                        continue
                    pub = format_pub_date(attrs.get("publishOn") or "")

                    rels = art.get("relationships") or {}
                    author_id = str((rels.get("author", {}).get("data") or {}).get("id") or "")
                    author_name = inc_authors.get(author_id, "Seeking Alpha Analyst")

                    # 精准匹配该作者对【当前查询股票】打出的评级（一篇文章点评多只股票时也不会串台）
                    rating_key = None
                    fallback_rk = None
                    sent_refs = (rels.get("sentiments", {}).get("data"))
                    if isinstance(sent_refs, dict):
                        sent_refs = [sent_refs]

                    if sent_refs:
                        for s_ref in sent_refs:
                            sid = str(s_ref.get("id") or "")
                            if sid in sent_map:
                                rk, st_id = sent_map[sid]
                                slug, name = tags_by_id.get(st_id, ("", ""))
                                if (tag_id_for_sym and st_id == tag_id_for_sym) or slug == symbol or name == symbol:
                                    rating_key = rk
                                    break
                                if fallback_rk is None:
                                    fallback_rk = rk
                        if rating_key is None:
                            rating_key = fallback_rk
                    elif art_id:
                        # 若列表未下发 sentiments 关系，单独补查该文章详情获取真实评级
                        rating_key = fetch_article_exact_rating(session, art_id, tag_id_for_sym, symbol)

                    articles.append({
                        "title_en": title,
                        "date": pub,
                        "author": author_name,
                        "rating_key": rating_key,  # 若官网本身无评级则为 None，绝不瞎编
                    })
    except Exception:
        pass

    # 若偶发网络异常未拿到 v3 JSON，回退官方 XML 分析流（仅取 /article/ 分析文章，并逐篇补查真实评级）
    if not articles:
        sa_xml_url = f"https://seekingalpha.com/api/sa/combined/{symbol}.xml"
        try:
            with cffi_requests.Session(impersonate="chrome") as session:
                r = session.get(sa_xml_url, timeout=12)
                if r.status_code == 200 and r.content:
                    root = ET.fromstring(r.content)
                    ns = {"sa": "https://seekingalpha.com/api/1.0"}
                    for item in root.findall("./channel/item"):
                        orig_link = (item.findtext("link") or "").strip()
                        if "/article/" not in orig_link:
                            continue
                        title = (item.findtext("title") or "").strip()
                        pub = format_pub_date(item.findtext("pubDate") or "")
                        author = (item.findtext("sa:author_name", namespaces=ns) or "").strip()
                        # 从链接提取 article_id，如 /article/4738291-xxx -> 4738291
                        art_id = orig_link.split("/article/")[-1].split("-")[0].split("?")[0]
                        rk = fetch_article_exact_rating(session, art_id, None, symbol) if art_id.isdigit() else None
                        if title:
                            articles.append({
                                "title_en": title,
                                "date": pub,
                                "author": author or "Seeking Alpha Analyst",
                                "rating_key": rk,
                            })
                        if len(articles) >= 15:
                            break
        except Exception:
            pass

    # 批量翻译英文标题为简体中文，并挂载官网真实评级样式
    if articles:
        zh_titles = translate_titles_to_zh([a["title_en"] for a in articles])
        for art, zh in zip(articles, zh_titles):
            art["title_zh"] = zh
            rk = art.get("rating_key")
            if rk and rk in RATING_MAP:
                label, css_cls = RATING_MAP[rk]
                art["rating_label"] = label
                art["rating_cls"] = css_cls
            else:
                art["rating_label"] = None
                art["rating_cls"] = None

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
