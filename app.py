import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import time
import html

# 请把邮箱改成你自己的（SEC 要求）
HEADERS = {"User-Agent": "PE-Website aihuaxiawenhua@gmail.com"}

# 你的 Seeking Alpha 专属推广链接
SA_REFERRAL_URL = (
    "https://seekingalpha.com/subscriptions/refer-a-friend"
    "?source=refer_friend_link&user_referrer=91b69c96c70651cc37407aca"
)

# 方案二：Apify 专门提取 Seeking Alpha 分析文章及作者评级的 Actor
APIFY_ACTOR_ID = "fortuitous_pirate~seekingalpha-stock-analysis-scraper"

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
        line-height: 1.48;
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
    /* 复刻 Seeking Alpha 官网经典评级色块（置于标题最前面） */
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
    s = str(raw_date).strip()
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        try:
            dt = pd.to_datetime(s)
            if dt.hour == 0 and dt.minute == 0 and len(s) <= 10:
                return dt.strftime("%Y-%m-%d")
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return s[:16]


RATING_MAP = {
    "strong_buy": ("强烈买入", "sa-strong-buy"),
    "strong buy": ("强烈买入", "sa-strong-buy"),
    "very_bullish": ("强烈买入", "sa-strong-buy"),
    "very bullish": ("强烈买入", "sa-strong-buy"),
    "buy": ("买入", "sa-buy"),
    "bullish": ("买入", "sa-buy"),
    "hold": ("持有", "sa-hold"),
    "neutral": ("持有", "sa-hold"),
    "sell": ("卖出", "sa-sell"),
    "bearish": ("卖出", "sa-sell"),
    "strong_sell": ("强烈卖出", "sa-strong-sell"),
    "strong sell": ("强烈卖出", "sa-strong-sell"),
    "very_bearish": ("强烈卖出", "sa-strong-sell"),
    "very bearish": ("强烈卖出", "sa-strong-sell"),
}


def normalize_rating_str(raw_rating):
    if raw_rating is None:
        return None
    s = str(raw_rating).strip().lower()
    if not s or s in ("none", "n/a", "null", "unknown"):
        return None
    k_space = s.replace("-", " ").replace("_", " ")
    k_under = k_space.replace(" ", "_")
    if k_space in RATING_MAP:
        return k_space
    if k_under in RATING_MAP:
        return k_under
    return None


def parse_apify_dataset_items(items, target_symbol):
    """从 Apify 数据集条目中提取纯分析文章和作者评级"""
    parsed = []
    if not isinstance(items, list):
        return parsed
    for item in items:
        if not isinstance(item, dict):
            continue
        # 校验该数据集是否属于当前查询的股票代码
        st_sym = str(item.get("search_ticker") or "").upper().strip()
        if st_sym and st_sym != target_symbol:
            continue

        title = (item.get("article_title") or item.get("title") or "").strip()
        if not title:
            continue
        atype = str(item.get("analysis_type") or "analysis").strip().lower()
        aurl = str(item.get("article_url") or item.get("url") or "")
        if atype == "news" or ("/news/" in aurl and "/article/" not in aurl):
            continue

        author = (item.get("author_name") or item.get("author") or "Seeking Alpha Analyst").strip()
        pub = format_pub_date(
            item.get("publish_date") or item.get("published_at") or item.get("date") or ""
        )
        raw_rating = (
            item.get("rating")
            or item.get("author_rating")
            or item.get("sentiment")
        )
        parsed.append({
            "title_en": title,
            "date": pub,
            "author": author,
            "rating_key": normalize_rating_str(raw_rating),
        })
    return parsed


def translate_titles_to_zh(titles):
    if not titles:
        return titles
    sep = "\n ||| \n"
    joined = sep.join(titles)
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": joined},
            timeout=(3, 8),
        )
        if r.status_code == 200:
            data = r.json()
            first_block = data[0] if data else []
            translated_full = "".join(seg[0] for seg in first_block if seg and seg[0])
            parts = [p.strip() for p in translated_full.split("|||")]
            if len(parts) == len(titles):
                return parts
    except Exception:
        pass
    return titles


def get_apify_token():
    try:
        return str(st.secrets.get("APIFY_API_TOKEN", "")).strip()
    except Exception:
        return ""


@st.cache_data(ttl=21600)
def load_seeking_alpha_feed(symbol, has_token):
    articles = []
    debug_notes = []
    token = get_apify_token() if has_token else ""

    if token:
        # 第 1 步（极速秒读）：检查 Apify 账号最近 10 次已跑完的历史记录里有没有同股票现成结果（6小时内）
        try:
            runs_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
            r_runs = requests.get(
                runs_url,
                params={"token": token, "desc": "true", "limit": 10},
                timeout=(4, 10),
            )
            if r_runs.status_code == 200:
                run_items = (r_runs.json().get("data") or {}).get("items") or []
                for run_info in run_items:
                    r_status = run_info.get("status")
                    ds_id = run_info.get("defaultDatasetId")
                    started_at = run_info.get("startedAt")
                    # 检查是否在最近 12 小时内
                    is_fresh = True
                    if started_at:
                        age_hours = (pd.Timestamp.now("UTC") - pd.to_datetime(started_at, utc=True)).total_seconds() / 3600.0
                        if age_hours > 12:
                            is_fresh = False

                    if r_status == "SUCCEEDED" and ds_id and is_fresh:
                        r_ds = requests.get(
                            f"https://api.apify.com/v2/datasets/{ds_id}/items",
                            params={"token": token},
                            timeout=(4, 10),
                        )
                        if r_ds.status_code == 200:
                            cand = parse_apify_dataset_items(r_ds.json(), symbol)
                            if cand:
                                articles = cand
                                sample_ratings = [c.get("rating_key") for c in cand[:5]]
                                debug_notes.append(f"命中Apify近期已完成数据集({ds_id[:8]}), 前5篇评级={sample_ratings}")
                                break
                    elif r_status == "RUNNING":
                        # 如果刚才点击触发的任务正在后台运行，直接复用等待它完成，不重复扣费！
                        run_id = run_info.get("id")
                        for _ in range(30):
                            time.sleep(4)
                            rc = requests.get(
                                f"https://api.apify.com/v2/actor-runs/{run_id}",
                                params={"token": token},
                                timeout=(4, 10),
                            )
                            if rc.status_code == 200:
                                rdata = rc.json().get("data") or {}
                                if rdata.get("status") == "SUCCEEDED":
                                    did = rdata.get("defaultDatasetId")
                                    rds = requests.get(
                                        f"https://api.apify.com/v2/datasets/{did}/items",
                                        params={"token": token},
                                        timeout=(4, 10),
                                    )
                                    if rds.status_code == 200:
                                        cand = parse_apify_dataset_items(rds.json(), symbol)
                                        if cand:
                                            articles = cand
                                            debug_notes.append(f"复用运行中任务完成({run_id[:8]})")
                                    break
                                if rdata.get("status") in ("FAILED", "ABORTED", "TIMED-OUT"):
                                    break
                        if articles:
                            break
        except Exception as e:
            debug_notes.append(f"查历史记录异常:{str(e)[:60]}")

        # 第 2 步：若没有近期同股票缓存，发起新的异步任务并每 4 秒轮询（最多等 160 秒，彻底告别单次连接超时！）
        if not articles:
            start_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs"
            # maxArticles 设为 8 篇，抓取速度加快一倍且更省额度！不强改默认代理配置以确保过盾成功率
            run_input = {
                "tickerSymbol": symbol,
                "analysisType": "analysis",
                "maxArticles": 8,
            }
            try:
                r_start = requests.post(
                    start_url,
                    params={"token": token},
                    json=run_input,
                    timeout=(5, 15),
                )
                if r_start.status_code in (200, 201):
                    run_data = r_start.json().get("data") or {}
                    run_id = run_data.get("id")
                    ds_id = run_data.get("defaultDatasetId")
                    final_status = "RUNNING"

                    for _ in range(40):  # 40 * 4秒 = 最多稳等 160 秒
                        time.sleep(4)
                        r_poll = requests.get(
                            f"https://api.apify.com/v2/actor-runs/{run_id}",
                            params={"token": token},
                            timeout=(4, 10),
                        )
                        if r_poll.status_code == 200:
                            pdata = r_poll.json().get("data") or {}
                            final_status = pdata.get("status")
                            ds_id = pdata.get("defaultDatasetId") or ds_id
                            if final_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                                break

                    if final_status == "SUCCEEDED" and ds_id:
                        r_items = requests.get(
                            f"https://api.apify.com/v2/datasets/{ds_id}/items",
                            params={"token": token},
                            timeout=(4, 12),
                        )
                        if r_items.status_code == 200:
                            raw_json = r_items.json()
                            cand = parse_apify_dataset_items(raw_json, symbol)
                            if cand:
                                articles = cand
                                sample_keys = list(raw_json[0].keys()) if isinstance(raw_json, list) and raw_json else []
                                sample_ratings = [c.get("rating_key") for c in cand[:5]]
                                debug_notes.append(f"新任务成功! 字段={sample_keys}, 前5评级={sample_ratings}")
                            else:
                                debug_notes.append(f"任务成功但返回条目数={len(raw_json) if isinstance(raw_json, list) else 0}")
                    else:
                        debug_notes.append(f"Apify任务结束状态={final_status}")
                else:
                    debug_notes.append(f"启动Apify返回HTTP {r_start.status_code}: {r_start.text[:120]}")
            except Exception as e:
                debug_notes.append(f"轮询异常:{str(e)[:80]}")

    # 保底通道：官方 XML 分析流
    if not articles:
        sa_xml_url = f"https://seekingalpha.com/api/sa/combined/{symbol}.xml"
        try:
            rx = requests.get(
                sa_xml_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    )
                },
                timeout=(3, 8),
            )
            if rx.status_code == 200 and rx.content:
                root = ET.fromstring(rx.content)
                ns = {"sa": "https://seekingalpha.com/api/1.0"}
                for item in root.findall("./channel/item"):
                    orig_link = (item.findtext("link") or "").strip()
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
                            "rating_key": None,
                        })
                    if len(articles) >= 10:
                        break
                debug_notes.append("回退官方XML流(不含评级)")
        except Exception:
            pass

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

    return articles, " | ".join(debug_notes)


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
    for concept in ("EarningsPerShareDiluted", "EarningsPerShareBasic"):
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

    merged = pd.concat([frame for _, _, frame in ep_frames], axis=1).sort_index().ffill()
    weights = pd.Series({sym: w for sym, w, _ in ep_frames})

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

with row2_left:
    with st.container(border=True):
        st.markdown("**🧩 预留模块 2（左下）**")
        st.markdown("""
            <div class="placeholder-box">
                <div>🚧 功能预留位</div>
                <div style="font-size: 0.85rem; margin-top: 6px;">例如：季度营收与净利润柱状图</div>
            </div>
        """, unsafe_allow_html=True)

with row2_right:
    with st.container(border=True):
        st.markdown("**🧩 预留模块 3（右下）**")
        st.markdown("""
            <div class="placeholder-box">
                <div>🚧 功能预留位</div>
                <div style="font-size: 0.85rem; margin-top: 6px;">例如：同行业多股票对比 / 自由现金流走势</div>
            </div>
        """, unsafe_allow_html=True)

detail_meta = None
sa_debug_msg = ""

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

# 【右上角】：Seeking Alpha 股票深度分析列表
with row1_right:
    with st.container(border=True):
        safe_ref_url = html.escape(SA_REFERRAL_URL, quote=True)
        has_apify = bool(get_apify_token())

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

        if not has_apify:
            st.caption("💡 提示：请在 Streamlit Secrets 中填入 `APIFY_API_TOKEN` 以显示官网精确作者评级。")

        if ticker:
            spinner_msg = (
                f"正在从 Seeking Alpha 同步 {ticker} 分析师评级（新股票首次约 40~90 秒，已有记录秒开）..."
                if has_apify else "正在拉取 Seeking Alpha 分析列表..."
            )
            with st.spinner(spinner_msg):
                sa_articles, sa_debug_msg = load_seeking_alpha_feed(ticker, has_apify)

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

                    badge_html = ""
                    if art.get("rating_label") and art.get("rating_cls"):
                        r_label = html.escape(art["rating_label"])
                        r_cls = html.escape(art["rating_cls"], quote=True)
                        badge_html = f'<span class="sa-rating {r_cls}">{r_label}</span>'

                    items_html.append(
                        f'<div class="sa-item">'
                        f'<div class="sa-title-line">'
                        f'{badge_html}'
                        f'<a href="{safe_ref_url}" target="_blank" rel="noopener noreferrer" title="{safe_title_en}">{safe_title_zh}</a>'
                        f'</div>'
                        f'<div class="sa-meta">{safe_author} &nbsp;·&nbsp; {safe_date}</div>'
                        f'</div>'
                    )
                st.markdown(
                    f'<div class="sa-scroll-box">{"".join(items_html)}</div>',
                    unsafe_allow_html=True,
                )

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
            if sa_debug_msg:
                st.caption(f"📡 Seeking Alpha 数据通道状态：{sa_debug_msg}")

st.caption("数据来源：Yahoo Finance、SEC EDGAR、Seeking Alpha，仅供参考，不构成投资建议。")
