import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import json
import re
import time
import html

# 请把邮箱改成你自己的（SEC 要求）
HEADERS = {"User-Agent": "PE-Website aihuaxiawenhua@gmail.com"}

# 你的 Seeking Alpha 专属推广链接
SA_REFERRAL_URL = (
    "https://seekingalpha.com/subscriptions/refer-a-friend"
    "?source=refer_friend_link&user_referrer=91b69c96c70651cc37407aca"
)

PUPPETEER_ACTOR_ID = "apify~puppeteer-scraper"
CACHE_SCHEMA_VER = "v3"

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
        border-bottom: 1px solid rgba(128, 1px, 128, 0.16);
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
    now_dt = pd.Timestamp.now()
    low = s.lower()
    if low.startswith("today"):
        return now_dt.strftime("%Y-%m-%d")
    if low.startswith("yesterday"):
        return (now_dt - pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        dt = parsedate_to_datetime(s)
        if dt.year < 1990:
            dt = dt.replace(year=now_dt.year)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    # 去掉星期前缀（如 "Sat, Nov. 14" -> "Nov 14"）以便精确补齐当前年份
    clean_s = re.sub(r"^[A-Za-z]{3},\s*", "", s).replace(".", "").strip()
    if not re.search(r"\b(19|20)\d{2}\b", clean_s):
        clean_s = f"{clean_s}, {now_dt.year}"

    try:
        dt = pd.to_datetime(clean_s)
        if dt.year < 1990:
            dt = dt.replace(year=now_dt.year)
        if dt > now_dt + pd.Timedelta(days=2):
            dt = dt.replace(year=now_dt.year - 1)
        if dt.hour == 0 and dt.minute == 0:
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

SA_SENTIMENT_ID_MAP = {
    "1": "buy",
    "2": "hold",
    "3": "sell",
    "4": "strong_buy",
    "5": "strong_sell",
}


def normalize_rating_str(raw_rating, allow_numeric=False):
    if raw_rating is None or isinstance(raw_rating, bool):
        return None
    s = str(raw_rating).strip().lower()
    if not s or s in ("none", "n/a", "null", "unknown", "no rating"):
        return None
    if allow_numeric and s in SA_SENTIMENT_ID_MAP:
        return SA_SENTIMENT_ID_MAP[s]
    k_space = s.replace("-", " ").replace("_", " ")
    k_under = k_space.replace(" ", "_")
    if k_space in RATING_MAP:
        return k_space
    if k_under in RATING_MAP:
        return k_under
    return None


def extract_rating_from_single_article_v3(art_json, symbol):
    """从单篇文章详情 /api/v3/articles/{id} 的 JSON 中精准提取当前股票评级"""
    if not isinstance(art_json, dict):
        return None
    included = art_json.get("included") or []
    data_obj = art_json.get("data") or {}
    sa_sym_up = symbol.upper().replace(".", "-")

    tags_by_id = {}
    for it in included:
        if it.get("type") == "tag":
            tid = str(it.get("id") or "")
            attrs = it.get("attributes") or {}
            slug = str(attrs.get("slug") or "").upper()
            name = str(attrs.get("name") or "").upper()
            tags_by_id[tid] = (slug, name)

    fallback_rk = None
    for it in included:
        itype = str(it.get("type") or "").lower()
        if "sentiment" in itype or "rating" in itype:
            attrs = it.get("attributes") or {}
            rk = None
            for fld in ("type", "rating", "label", "slug", "sentimentId", "sentiment_id"):
                is_num = "id" in fld.lower()
                rk = normalize_rating_str(attrs.get(fld), allow_numeric=is_num)
                if rk:
                    break
            if not rk:
                for k, v in attrs.items():
                    if isinstance(v, (str, int)):
                        rk = normalize_rating_str(v, allow_numeric=("id" in k.lower()))
                        if rk:
                            break
            if rk:
                rels = it.get("relationships") or {}
                tag_id = str((rels.get("tag", {}).get("data") or {}).get("id") or "")
                slug, name = tags_by_id.get(tag_id, ("", ""))
                if slug in (symbol, sa_sym_up) or name in (symbol, sa_sym_up):
                    return rk
                if fallback_rk is None:
                    fallback_rk = rk

    # 兜底检查 data.attributes 自身字段
    d_attrs = data_obj.get("attributes") or {}
    for k, v in d_attrs.items():
        if any(w in k.lower() for w in ("sent", "rat")) and isinstance(v, (str, int)):
            rk = normalize_rating_str(v, allow_numeric=("id" in k.lower()))
            if rk:
                return rk

    return fallback_rk


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


def run_puppeteer_v3_details(token, symbol, proxy_cfg):
    sa_sym = symbol.lower().replace(".", "-")
    # 核心突破：在已过盾的同源浏览器中提取前 10 篇分析文章 ID，并并发请求每篇文章的 /api/v3/articles/{id}?include=sentiments,sentiments.tag 详情接口！
    page_fn = """
    async function pageFunction(context) {
        const { page, request } = context;
        const sym = request.userData.symbol || 'AAPL';

        // 等待文章列表渲染完成
        try {
            await page.waitForSelector('article', { timeout: 15000 });
        } catch (e) {}
        await new Promise(r => setTimeout(r, 2000));

        // 1. 从分析列表提取前 10 篇文章的标题、作者、日期以及 articleId
        const cards = await page.evaluate(() => {
            const items = Array.from(document.querySelectorAll('article'));
            const out = [];
            const seen = new Set();
            for (const el of items) {
                const aTitle = el.querySelector('a[data-test-id="post-list-item-title"], h3 a, a[href*="/article/"]');
                if (!aTitle) continue;
                const href = aTitle.getAttribute('href') || '';
                const m = href.match(/\\/article\\/(\\d+)/);
                if (!m) continue;
                const aid = m[[1]](#__1);
                if (seen.has(aid)) continue;
                seen.add(aid);

                const title = (aTitle.textContent || '').trim();
                if (!title || title.toLowerCase().startsWith('wall street breakfast')) continue;

                const aAuthor = el.querySelector('a[data-test-id="post-list-author"], a[href*="/author/"]');
                const tDate = el.querySelector('span[data-test-id="post-list-date"], time');
                out.push({
                    id: aid,
                    href: href,
                    title: title,
                    author: aAuthor ? aAuthor.textContent.trim() : 'Seeking Alpha Analyst',
                    date: tDate ? (tDate.getAttribute('datetime') || tDate.textContent.trim()) : ''
                });
                if (out.length >= 10) break;
            }
            return out;
        });

        // 2. 在同源浏览器内并发拉取每篇文章的原生详情 API：/api/v3/articles/{id}?include=sentiments,sentiments.tag,author
        const enriched = await page.evaluate(async (cardList) => {
            const tasks = cardList.map(async (c) => {
                let detailJson = null;
                let detailStatus = 0;
                let htmlRating = null;

                for (const inc of ['sentiments,sentiments.tag,author', 'sentiments']) {
                    try {
                        const r = await fetch(`/api/v3/articles/${c.id}?include=${inc}`, {
                            credentials: 'same-origin',
                            headers: { 'accept': 'application/json' }
                        });
                        detailStatus = r.status;
                        if (r.status === 200) {
                            detailJson = await r.json();
                            break;
                        }
                    } catch (e) {}
                }

                // 若 v3 接口未带 sentiments，再快速检查无 include 的默认文章详情接口
                if (!detailJson) {
                    try {
                        const r2 = await fetch(`/api/v3/articles/${c.id}`, {
                            credentials: 'same-origin',
                            headers: { 'accept': 'application/json' }
                        });
                        detailStatus = r2.status;
                        if (r2.status === 200) {
                            detailJson = await r2.json();
                        }
                    } catch (e) {}
                }

                // 精简保存关键字段（减小体积并保留第1篇完整结构供核对）
                let slimDetail = null;
                if (detailJson) {
                    slimDetail = {
                        included: detailJson.included || [],
                        data: {
                            id: (detailJson.data || {}).id,
                            attributes: {
                                publishOn: ((detailJson.data || {}).attributes || {}).publishOn,
                                title: ((detailJson.data || {}).attributes || {}).title,
                                sentiments: ((detailJson.data || {}).attributes || {}).sentiments,
                                rating: ((detailJson.data || {}).attributes || {}).rating
                            },
                            relationships: ((detailJson.data || {}).relationships || {})
                        }
                    };
                }

                return {
                    ...c,
                    detailStatus,
                    detail: slimDetail,
                    htmlRating
                };
            });
            return await Promise.all(tasks);
        }, cards);

        return {
            schema: 'v3',
            symbol: sym.toUpperCase(),
            count: enriched.length,
            items: enriched
        };
    }
    """
    pup_input = {
        "startUrls": [{
            "url": f"https://seekingalpha.com/symbol/{sa_sym}/analysis",
            "userData": {"symbol": symbol},
        }],
        "linkSelector": "",
        "pageFunction": page_fn,
        "proxyConfiguration": proxy_cfg,
        "useChrome": True,
        "maxPagesPerCrawl": 1,
        "maxRequestRetries": 2,
        "pageLoadTimeoutSecs": 45,
    }
    r_start = requests.post(
        f"https://api.apify.com/v2/acts/{PUPPETEER_ACTOR_ID}/runs",
        params={"token": token},
        json=pup_input,
        timeout=(5, 15),
    )
    if r_start.status_code not in (200, 201):
        return None, f"启动HTTP {r_start.status_code}"

    rdata = r_start.json().get("data") or {}
    run_id = rdata.get("id")
    ds_id = rdata.get("defaultDatasetId")
    f_status = "RUNNING"

    for _ in range(30):
        time.sleep(3)
        rp = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}",
            params={"token": token},
            timeout=(4, 10),
        )
        if rp.status_code == 200:
            pd_obj = rp.json().get("data") or {}
            f_status = pd_obj.get("status")
            ds_id = pd_obj.get("defaultDatasetId") or ds_id
            if f_status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

    if f_status == "SUCCEEDED" and ds_id:
        ri = requests.get(
            f"https://api.apify.com/v2/datasets/{ds_id}/items",
            params={"token": token},
            timeout=(4, 10),
        )
        if ri.status_code == 200:
            arr = ri.json()
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                return arr[0], f"SUCCEEDED(run={run_id[:8]})"
    return None, f"状态={f_status}"


def parse_v3_enriched_record(rec, symbol):
    items = rec.get("items") or []
    out = []
    statuses = []
    first_detail_diag = ""

    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        detail = it.get("detail")
        statuses.append(it.get("detailStatus"))

        pub_iso = ""
        if isinstance(detail, dict):
            pub_iso = ((detail.get("data") or {}).get("attributes") or {}).get("publishOn") or ""
        pub = format_pub_date(pub_iso or it.get("date") or "")
        author = (it.get("author") or "Seeking Alpha Analyst").strip()

        rk = extract_rating_from_single_article_v3(detail, symbol)
        if not rk and it.get("htmlRating"):
            rk = normalize_rating_str(it.get("htmlRating"))

        if idx == 0 and isinstance(detail, dict):
            inc = detail.get("included") or []
            inc_summary = [(x.get("type"), x.get("attributes")) for x in inc if "author" not in str(x.get("type"))]
            rels_keys = list(((detail.get("data") or {}).get("relationships") or {}).keys())
            first_detail_diag = f"首篇HTTP={it.get('detailStatus')}, rels={rels_keys}, inc={json.dumps(inc_summary, ensure_ascii=False)[:220]}"

        out.append({
            "title_en": title,
            "date": pub,
            "author": author,
            "rating_key": rk,
        })

    ratings_preview = [x.get("rating_key") for x in out[:5]]
    diag = f"详情HTTP状态={statuses[:5]}, 前5评级={ratings_preview}"
    if not any(ratings_preview) and first_detail_diag:
        diag += f" | {first_detail_diag}"
    return out, diag


@st.cache_data(ttl=21600)
def load_seeking_alpha_feed(symbol, has_token, _schema=CACHE_SCHEMA_VER):
    articles = []
    debug_notes = []
    token = get_apify_token() if has_token else ""

    if token:
        # 1. 先检查最近 6 小时内是否已有 schema=='v3' 的同股票缓存结果
        try:
            r_hist = requests.get(
                f"https://api.apify.com/v2/acts/{PUPPETEER_ACTOR_ID}/runs",
                params={"token": token, "desc": "true", "limit": 10},
                timeout=(4, 10),
            )
            if r_hist.status_code == 200:
                for run_info in (r_hist.json().get("data") or {}).get("items") or []:
                    ds_id = run_info.get("defaultDatasetId")
                    started_at = run_info.get("startedAt")
                    fresh = True
                    if started_at:
                        age_h = (pd.Timestamp.now("UTC") - pd.to_datetime(started_at, utc=True)).total_seconds() / 3600.0
                        if age_h > 6:
                            fresh = False
                    if run_info.get("status") == "SUCCEEDED" and ds_id and fresh:
                        rds = requests.get(
                            f"https://api.apify.com/v2/datasets/{ds_id}/items",
                            params={"token": token},
                            timeout=(4, 10),
                        )
                        if rds.status_code == 200:
                            arr = rds.json()
                            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                                rec = arr[0]
                                if rec.get("schema") == "v3" and str(rec.get("symbol") or "").upper() == symbol:
                                    cand, diag = parse_v3_enriched_record(rec, symbol)
                                    if cand:
                                        articles = cand
                                        debug_notes.append(f"命中v3缓存({ds_id[:8]}) | {diag}")
                                        break
        except Exception:
            pass

        # 2. 若无 v3 缓存，启动住宅代理并发读取单篇详情接口
        if not articles:
            proxy_cfg = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}
            try:
                rec, note = run_puppeteer_v3_details(token, symbol, proxy_cfg)
                debug_notes.append(f"住宅代理v3:{note}")
                if rec:
                    cand, diag = parse_v3_enriched_record(rec, symbol)
                    debug_notes.append(diag)
                    if cand:
                        articles = cand
            except Exception as e:
                debug_notes.append(f"v3异常:{str(e)[:60]}")

    # 保底通道
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
                    if not title or title.lower().startswith("wall street breakfast"):
                        continue
                    pub = format_pub_date(item.findtext("pubDate") or "")
                    author = (item.findtext("sa:author_name", namespaces=ns) or "").strip()
                    articles.append({
                        "title_en": title,
                        "date": pub,
                        "author": author or "Seeking Alpha Analyst",
                        "rating_key": None,
                    })
                    if len(articles) >= 10:
                        break
                debug_notes.append("回退官方XML流")
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
                f"正在从 Seeking Alpha 逐篇读取 {ticker} 详情评级（约 20~35 秒，之后 6 小时秒开）..."
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
