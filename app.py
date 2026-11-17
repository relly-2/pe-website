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
CACHE_SCHEMA_VER = "v2"

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

    clean_s = s.replace(".", "")
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


def scan_rating_in_obj(obj):
    """递归扫描任意 JSON 对象中的所有字段，自动识别评级枚举词或 sentimentId"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            is_num_rating_field = kl in ("sentimentid", "sentiment_id", "ratingid", "rating_id")
            if isinstance(v, (str, int, float)):
                rk = normalize_rating_str(v, allow_numeric=is_num_rating_field)
                if rk:
                    return rk
            elif isinstance(v, (dict, list)):
                rk = scan_rating_in_obj(v)
                if rk:
                    return rk
    elif isinstance(obj, list):
        for elem in obj:
            rk = scan_rating_in_obj(elem)
            if rk:
                return rk
    return None


def inspect_v3_structure(payload):
    """生成一行精简诊断摘要，看清 SA 返回的真实 JSON 字段名"""
    if not isinstance(payload, dict):
        return f"v3非dict({type(payload).__name__})"
    d_list = payload.get("data") or []
    inc_list = payload.get("included") or []
    inc_types = {}
    sent_sample = None
    for it in inc_list:
        t = str(it.get("type"))
        inc_types[t] = inc_types.get(t, 0) + 1
        if ("sent" in t.lower() or "rat" in t.lower()) and sent_sample is None:
            sent_sample = it
    art_rels = []
    art_rating_fields = {}
    if d_list and isinstance(d_list[0], dict):
        a0 = d_list[0]
        art_rels = list((a0.get("relationships") or {}).keys())
        attrs0 = a0.get("attributes") or {}
        for k, v in attrs0.items():
            if any(w in k.lower() for w in ("sent", "rat", "bull", "bear", "quant", "sell", "buy")):
                art_rating_fields[k] = v
    return (
        f"inc类型={inc_types}, 文章rels={art_rels}, "
        f"文章评级相关属性={art_rating_fields}, "
        f"首个sentiment样例={json.dumps(sent_sample, ensure_ascii=False)[:180] if sent_sample else '无'}"
    )


def parse_v3_json_payload(payload, symbol):
    out = []
    if not isinstance(payload, dict):
        return out
    data_list = payload.get("data") or []
    included = payload.get("included") or []
    sa_sym_up = symbol.upper().replace(".", "-")

    inc_by_key = {}
    inc_authors = {}
    tags_by_id = {}
    target_tag_id = None

    for item in included:
        itype = str(item.get("type") or "")
        iid = str(item.get("id") or "")
        inc_by_key[(itype, iid)] = item
        attrs = item.get("attributes") or {}
        if itype == "author":
            inc_authors[iid] = (attrs.get("nick") or "Seeking Alpha Analyst").strip()
        elif itype == "tag":
            slug = (attrs.get("slug") or "").upper()
            name = (attrs.get("name") or "").upper()
            tags_by_id[iid] = (slug, name)
            if slug in (symbol, sa_sym_up) or name in (symbol, sa_sym_up):
                target_tag_id = iid

    sent_map = {}
    for item in included:
        itype = str(item.get("type") or "")
        if "sentiment" in itype.lower() or "rating" in itype.lower():
            sid = str(item.get("id") or "")
            attrs = item.get("attributes") or {}
            rk = scan_rating_in_obj(attrs)
            rels = item.get("relationships") or {}
            if not rk:
                rk = scan_rating_in_obj(rels)
            st_id = str((rels.get("tag", {}).get("data") or {}).get("id") or "")
            if rk:
                sent_map[sid] = (rk, st_id)

    for art in data_list:
        if art.get("type") != "article":
            continue
        attrs = art.get("attributes") or {}
        title = (attrs.get("title") or "").strip()
        if not title or title.lower().startswith("wall street breakfast"):
            continue
        pub = format_pub_date(attrs.get("publishOn") or "")

        rels = art.get("relationships") or {}
        author_id = str((rels.get("author", {}).get("data") or {}).get("id") or "")
        author_name = inc_authors.get(author_id, "Seeking Alpha Analyst")

        rating_key = None
        fallback_rk = None

        # 1. 从 relationships.sentiments 查找
        for rel_name, rel_obj in rels.items():
            if "sent" in rel_name.lower() or "rat" in rel_name.lower():
                refs = (rel_obj or {}).get("data")
                if isinstance(refs, dict):
                    refs = [refs]
                if isinstance(refs, list):
                    for s_ref in refs:
                        sid = str(s_ref.get("id") or "")
                        stype = str(s_ref.get("type") or "")
                        if sid in sent_map:
                            rk, st_id = sent_map[sid]
                            slug, name = tags_by_id.get(st_id, ("", ""))
                            if (target_tag_id and st_id == target_tag_id) or slug in (symbol, sa_sym_up) or name in (symbol, sa_sym_up):
                                rating_key = rk
                                break
                            if fallback_rk is None:
                                fallback_rk = rk
                        elif (stype, sid) in inc_by_key:
                            rk = scan_rating_in_obj(inc_by_key[(stype, sid)].get("attributes") or {})
                            if rk and fallback_rk is None:
                                fallback_rk = rk
            if rating_key:
                break

        if not rating_key:
            rating_key = fallback_rk

        # 2. 如果文章 attributes 自身直接带有评级字段，扫描提取
        if not rating_key:
            for k, v in attrs.items():
                if any(w in k.lower() for w in ("sent", "rat")):
                    rk = scan_rating_in_obj({k: v})
                    if rk:
                        rating_key = rk
                        break

        out.append({
            "title_en": title,
            "date": pub,
            "author": author_name,
            "rating_key": rating_key,
        })
    return out


def parse_dom_cards(dom_cards):
    out = []
    if not isinstance(dom_cards, list):
        return out
    for c in dom_cards:
        if not isinstance(c, dict):
            continue
        title = (c.get("title") or "").strip()
        if not title or title.lower().startswith("wall street breakfast"):
            continue
        out.append({
            "title_en": title,
            "date": format_pub_date(c.get("date") or ""),
            "author": (c.get("author") or "Seeking Alpha Analyst").strip(),
            "rating_key": normalize_rating_str(c.get("rating")),
        })
    return out


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


def run_puppeteer_once(token, symbol, proxy_cfg):
    sa_sym = symbol.lower().replace(".", "-")
    # 同时拦截网页原生发出的 /articles API 数据包 + 等待评级徽章渲染后提取 DOM 文本
    page_fn = """
    async function pageFunction(context) {
        const { page, request } = context;
        const sym = request.userData.symbol || 'AAPL';
        const sLow = sym.toLowerCase().replace('.', '-');

        // 稍微向下滚动触发懒加载评级组件渲染，并等待 3.5 秒
        try {
            await page.evaluate(() => window.scrollBy(0, 500));
        } catch (e) {}
        await new Promise(r => setTimeout(r, 3500));

        // 方式1：请求不带多余限制参数的默认 /articles 接口（与 SA 前端默认请求一致）以及显式带 sentiments 的接口
        let v3Res = { status: 0, body: null, urlUsed: '' };
        try {
            v3Res = await page.evaluate(async (s) => {
                const urls = [
                    `/api/v3/symbols/${s}/articles?filter[category]=latest-articles&page[size]=14&include=author,primaryTickers,secondaryTickers,sentiments,sentiments.tag`,
                    `/api/v3/symbols/${s}/articles?page[size]=14`
                ];
                for (const u of urls) {
                    const r = await fetch(u, { credentials: 'same-origin', headers: { 'accept': 'application/json' } });
                    if (r.status === 200) {
                        const jb = await r.json();
                        if (jb && jb.data && jb.data.length > 0) {
                            return { status: 200, body: jb, urlUsed: u };
                        }
                    }
                }
                return { status: -2, body: null, urlUsed: '' };
            }, sLow);
        } catch (err) {
            v3Res = { status: -1, err: String(err) };
        }

        // 方式2：扫描页面上所有文章卡片元素及评级胶囊（兼容 button / span / div / data-test-id）
        let domCards = [];
        try {
            domCards = await page.evaluate(() => {
                const ratingSet = new Set(['strong buy', 'buy', 'hold', 'sell', 'strong sell']);
                const cards = Array.from(document.querySelectorAll('article, [data-test-id="post-list-item"]'));
                return cards.slice(0, 14).map(el => {
                    const tEl = el.querySelector('a[data-test-id="post-list-item-title"], h3 a, a[href*="/article/"]');
                    const aEl = el.querySelector('a[data-test-id="post-list-author"], a[href*="/author/"]');
                    const timeEl = el.querySelector('span[data-test-id="post-list-date"], time');
                    let foundRating = null;
                    const nodes = Array.from(el.querySelectorAll('[data-test-id*="rating"], button, span, div'));
                    for (const nd of nodes) {
                        if (nd.children.length === 0) {
                            const tx = (nd.textContent || '').trim().toLowerCase();
                            if (ratingSet.has(tx)) {
                                foundRating = tx;
                                break;
                            }
                        }
                    }
                    return {
                        title: tEl ? tEl.textContent.trim() : '',
                        author: aEl ? aEl.textContent.trim() : '',
                        date: timeEl ? (timeEl.getAttribute('datetime') || timeEl.textContent.trim()) : '',
                        rating: foundRating,
                        cardTextSample: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 140)
                    };
                }).filter(x => x.title);
            });
        } catch (e) {}

        return {
            schema: 'v2',
            symbol: sym.toUpperCase(),
            pageTitle: await page.title(),
            status: v3Res.status,
            v3_body: v3Res.body,
            dom_cards: domCards
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


def merge_and_diagnose(rec, symbol):
    v3_body = rec.get("v3_body")
    dom_cards = rec.get("dom_cards") or []
    cand = parse_v3_json_payload(v3_body, symbol)
    dom_cand = parse_dom_cards(dom_cards)

    if cand and dom_cand:
        dom_map = {d["title_en"]: d["rating_key"] for d in dom_cand if d.get("rating_key")}
        for c in cand:
            if not c.get("rating_key") and c["title_en"] in dom_map:
                c["rating_key"] = dom_map[c["title_en"]]

    final_cand = cand if cand else dom_cand
    ratings_preview = [c.get("rating_key") for c in final_cand[:5]]

    diag = f"前5评级={ratings_preview}"
    # 如果仍然全是 None，把刚才抓到的真实 JSON 字段结构摘要打印出来，一眼看穿
    if not any(ratings_preview):
        v3_diag = inspect_v3_structure(v3_body)
        dom_sample = dom_cards[0].get("cardTextSample", "") if dom_cards else "无DOM卡片"
        diag += f" | 结构诊断: {v3_diag} | 首卡片文本={dom_sample}"
    return final_cand, diag


@st.cache_data(ttl=21600)
def load_seeking_alpha_feed(symbol, has_token, _schema=CACHE_SCHEMA_VER):
    articles = []
    debug_notes = []
    token = get_apify_token() if has_token else ""

    if token:
        # 1. 先检查最近 6 小时内已跑成功的同股票数据集（可直接复用刚才跑成功的 u7M1oQoF，不用重新跑！）
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
                                if str(rec.get("symbol") or "").upper() == symbol:
                                    final_cand, diag = merge_and_diagnose(rec, symbol)
                                    # 若旧缓存是 v1 且没抓到评级，允许再跑一次带滚动的 v2；若已是 v2 或已有评级则直接秒用
                                    if final_cand and (any(c.get("rating_key") for c in final_cand) or rec.get("schema") == "v2"):
                                        articles = final_cand
                                        debug_notes.append(f"命中缓存({ds_id[:8]}) | {diag}")
                                        break
                                    elif final_cand:
                                        # 先记录下来旧缓存的结构诊断信息
                                        debug_notes.append(f"旧缓存诊断({ds_id[:8]}): {diag}")
                                        break
        except Exception as e:
            debug_notes.append(f"读缓存异常:{str(e)[:50]}")

        # 2. 若还没有带评级的结果，用 v2 脚本跑一次住宅代理
        if not articles:
            proxy_cfg = {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]}
            try:
                rec, note = run_puppeteer_once(token, symbol, proxy_cfg)
                debug_notes.append(f"住宅代理v2:{note}")
                if rec:
                    final_cand, diag = merge_and_diagnose(rec, symbol)
                    if final_cand:
                        articles = final_cand
                        debug_notes.append(diag)
            except Exception as e:
                debug_notes.append(f"住宅代理异常:{str(e)[:60]}")

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
                f"正在从 Seeking Alpha 官网接口同步 {ticker} 每篇评级（约 20~35 秒，之后秒开）..."
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
