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
CACHE_SCHEMA_VER = "v6"          # 升级版本号，旧的 v5 失败数据集不再被复用
SA_FAIL_RETRY_SECS = 900         # 抓评级失败后，15 分钟内不重复启动 Apify
SA_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
        "时间范围", [1, 3, 5, 10, 20], index=4,
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


def normalize_rating_str(raw_rating):
    """只认明确的文字评级；不再把数字 ID 猜成评级（宁可不显示，也不显示错）。"""
    if raw_rating is None or isinstance(raw_rating, bool):
        return None
    s = str(raw_rating).strip().lower()
    if not s or s in ("none", "n/a", "null", "unknown", "no rating"):
        return None
    k_space = s.replace("-", " ").replace("_", " ")
    k_under = k_space.replace(" ", "_")
    if k_space in RATING_MAP:
        return k_space
    if k_under in RATING_MAP:
        return k_under
    return None


def pick_unambiguous_rating(rating_keys):
    """多个候选评级时：全部一致才采用，互相矛盾则放弃。"""
    keys = [k for k in rating_keys if k in RATING_MAP]
    if not keys:
        return None
    labels = {RATING_MAP[k][0] for k in keys}
    if len(labels) == 1:
        return keys[0]
    return None


def extract_rating_from_single_article_v3(art_json, symbol):
    if not isinstance(art_json, dict):
        return None
    included = art_json.get("included") or []
    data_obj = art_json.get("data") or {}
    sa_sym_up = symbol.upper().replace(".", "-")

    tags_by_id = {}
    for it in included:
        if isinstance(it, dict) and it.get("type") == "tag":
            tid = str(it.get("id") or "")
            attrs = it.get("attributes") or {}
            slug = str(attrs.get("slug") or "").upper()
            name = str(attrs.get("name") or "").upper()
            tags_by_id[tid] = (slug, name)

    unmatched = []
    for it in included:
        if not isinstance(it, dict):
            continue
        itype = str(it.get("type") or "").lower()
        if "sentiment" not in itype and "rating" not in itype:
            continue
        attrs = it.get("attributes") or {}
        rk = None
        for fld in ("type", "rating", "label", "slug", "name"):
            rk = normalize_rating_str(attrs.get(fld))
            if rk:
                break
        if not rk:
            continue
        rels = it.get("relationships") or {}
        tag_data = (rels.get("tag") or {}).get("data") or {}
        tag_id = str(tag_data.get("id") or "") if isinstance(tag_data, dict) else ""
        slug, name = tags_by_id.get(tag_id, ("", ""))
        if slug in (symbol, sa_sym_up) or name in (symbol, sa_sym_up):
            return rk  # 明确对应当前股票的评级
        unmatched.append(rk)

    d_attrs = data_obj.get("attributes") or {}
    for k in ("rating", "sentiment"):
        v = d_attrs.get(k)
        if isinstance(v, str):
            rk = normalize_rating_str(v)
            if rk:
                return rk

    # 无法按股票匹配时：只有全部一致才采用（避免多股票文章张冠李戴）
    return pick_unambiguous_rating(unmatched)


def extract_rating_from_ssr_snippet(snippet):
    if not snippet:
        return None
    s = str(snippet).replace('\\"', '"')
    pat = (
        r'"(?:type|rating|slug|label|name)"\s*:\s*"'
        r'(strong[_ -]?buy|very[_ -]?bullish|buy|bullish|hold|neutral|'
        r'sell|bearish|strong[_ -]?sell|very[_ -]?bearish)"'
    )
    found = []
    for m in re.finditer(pat, s, flags=re.IGNORECASE):
        rk = normalize_rating_str(m.group(1))
        if rk:
            found.append(rk)
    return pick_unambiguous_rating(found)


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


def fetch_sa_xml_articles(symbol, limit):
    """从 Seeking Alpha 官方 XML 取最新分析文章清单（不含评级）。"""
    out = []
    rx = requests.get(
        f"https://seekingalpha.com/api/sa/combined/{symbol}.xml",
        headers={"User-Agent": SA_BROWSER_UA},
        timeout=(4, 10),
    )
    if rx.status_code != 200 or not rx.content:
        return out
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
        out.append({
            "order": len(out),
            "url": orig_link.split("?")[0],
            "title_en": title,
            "date": pub,
            "author": author or "Seeking Alpha Analyst",
            "rating_key": None,
        })
        if len(out) >= limit:
            break
    return out


def finalize_articles(articles):
    """补充中文标题与评级徽章字段。"""
    if not articles:
        return articles
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


SA_FIRST_WAIT_SECS = 100      # 新启动抓取后，页面最多同步等待的秒数
SA_RECHECK_WAIT_SECS = 20     # 之后每次刷新页面，最多再等待的秒数
SA_PENDING_MAX_SECS = 1800    # 超过 30 分钟仍未完成的任务直接放弃
SA_RUN_TIMEOUT_SECS = 300     # Apify 端单次运行的时间上限
SA_TERMINAL = ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT")


class SARatingUnavailable(Exception):
    """没抓到任何评级。抛异常可让 st.cache_data 不缓存这次失败结果。"""
    pass


class SARatingPending(SARatingUnavailable):
    """Apify 任务还在跑，下次刷新页面时继续检查同一个任务。"""
    pass


@st.cache_resource
def _sa_state_registry():
    """保存：各股票最近一次失败时间 + 尚未跑完的 Apify 任务。"""
    return {}


def start_puppeteer_run(token, symbol, schema_ver):
    """启动 Apify 任务，立即返回 (run_id, dataset_id, 说明)，不在这里等待。"""
    base_articles = fetch_sa_xml_articles(symbol, 8)
    if not base_articles:
        return None, None, "XML未找到分析文章"

    start_urls = [
        {
            "url": a["url"],
            "userData": {
                "schema": schema_ver,
                "symbol": symbol,
                "order": a["order"],
                "title_en": a["title_en"],
                "date": a["date"],
                "author": a["author"],
            },
        }
        for a in base_articles
    ]

    pre_nav_hook = r"""
    [
        async (crawlingContext, gotoOptions) => {
            const { page, request } = crawlingContext;
            request.userData._capturedV3 = null;

            await page.setRequestInterception(true);
            page.on('request', (req) => {
                const rType = req.resourceType();
                if (['image', 'media', 'font'].includes(rType)) {
                    req.abort();
                } else {
                    req.continue();
                }
            });

            page.on('response', async (res) => {
                try {
                    if (request.userData._capturedV3) return;                 // 不覆盖已截获的结果
                    const u = res.url();
                    if (!/\/api\/v3\/articles\/\d+(\?|$)/.test(u)) return;    // 只认文章本体
                    if (res.status() !== 200) return;
                    const jb = await res.json();
                    if (jb && jb.data && !Array.isArray(jb.data)) {
                        const a = jb.data.attributes || {};
                        request.userData._capturedV3 = {
                            included: jb.included || [],
                            data: {
                                id: jb.data.id,
                                attributes: { sentiments: a.sentiments, rating: a.rating, sentiment: a.sentiment },
                                relationships: jb.data.relationships || {}
                            }
                        };
                    }
                } catch (e) {}
            });
            gotoOptions.waitUntil = 'domcontentloaded';
        }
    ]
    """

    page_fn = r"""
    async function pageFunction(context) {
        const { page, request } = context;
        await new Promise(r => setTimeout(r, 2500));

        const info = await page.evaluate(() => {
            const htmlTxt = document.documentElement.innerHTML || '';
            const blocked = /px-captcha|press\s*&(amp;)?\s*hold|access to this page has been denied/i.test(htmlTxt);

            const snippets = [];
            const re = /\\?"type\\?"\s*:\s*\\?"sentiment\\?"/g;
            let m;
            while ((m = re.exec(htmlTxt)) !== null && snippets.length < 6) {
                snippets.push(htmlTxt.slice(Math.max(0, m.index - 200), m.index + 300));
            }

            const headerEl = document.querySelector('article') || document.body;
            return {
                blocked: blocked,
                ssrSnippet: snippets.join(' ### '),
                headText: (headerEl.innerText || '').replace(/\s+/g, ' ').slice(0, 360)
            };
        });

        // 被反爬拦截：只换会话重试 1 次；第二次仍被拦就如实返回，方便诊断
        if (info.blocked && (request.retryCount || 0) < 1) {
            try { if (context.session && context.session.retire) context.session.retire(); } catch (e) {}
            throw new Error('PX_BLOCKED');
        }

        return {
            schema: request.userData.schema,
            symbol: request.userData.symbol,
            order: request.userData.order,
            title_en: request.userData.title_en,
            date: request.userData.date,
            author: request.userData.author,
            blocked: info.blocked,
            capturedV3: request.userData._capturedV3,
            ssrSnippet: info.ssrSnippet,
            headText: info.headText
        };
    }
    """

    pup_input = {
        "startUrls": start_urls,
        "linkSelector": "",
        "preNavigationHooks": pre_nav_hook,
        "pageFunction": page_fn,
        "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
        "useChrome": True,
        "maxConcurrency": 8,
        "maxPagesPerCrawl": 8,
        "maxRequestRetries": 1,
        "pageLoadTimeoutSecs": 30,
    }

    r_start = requests.post(
        f"https://api.apify.com/v2/acts/{PUPPETEER_ACTOR_ID}/runs",
        params={"token": token, "timeout": SA_RUN_TIMEOUT_SECS},
        json=pup_input,
        timeout=(5, 15),
    )
    if r_start.status_code not in (200, 201):
        return None, None, f"启动HTTP {r_start.status_code}"

    rdata = r_start.json().get("data") or {}
    run_id = rdata.get("id")
    if not run_id:
        return None, None, "启动响应里没有run id"
    return run_id, rdata.get("defaultDatasetId"), "已启动"


def wait_for_run(token, run_id, max_secs):
    """轮询任务状态，最多等 max_secs 秒。返回 (状态, dataset_id)。"""
    status, ds_id = "RUNNING", None
    deadline = time.time() + max_secs
    while True:
        try:
            rp = requests.get(
                f"https://api.apify.com/v2/actor-runs/{run_id}",
                params={"token": token},
                timeout=(4, 10),
            )
            if rp.status_code == 200:
                pd_obj = rp.json().get("data") or {}
                status = pd_obj.get("status") or status
                ds_id = pd_obj.get("defaultDatasetId") or ds_id
        except requests.RequestException:
            pass
        if status in SA_TERMINAL or time.time() >= deadline:
            break
        time.sleep(3)
    return status, ds_id


def fetch_dataset_items(token, ds_id):
    try:
        ri = requests.get(
            f"https://api.apify.com/v2/datasets/{ds_id}/items",
            params={"token": token},
            timeout=(4, 10),
        )
        if ri.status_code == 200:
            arr = ri.json()
            if isinstance(arr, list):
                return arr
    except Exception:
        pass
    return []


_SSR_RATING_PAT = (
    r'"(?:type|rating|slug|label|name)"\s*:\s*"'
    r'(strong[_ -]?buy|very[_ -]?bullish|buy|bullish|hold|neutral|'
    r'sell|bearish|strong[_ -]?sell|very[_ -]?bearish)"'
)


def _row_debug(row):
    """把单篇文章实际抓到的内容整理成可读的诊断文本。"""
    cap = row.get("capturedV3")
    if isinstance(cap, dict):
        inc = [it for it in (cap.get("included") or []) if isinstance(it, dict)]
        sent = [
            it for it in inc
            if any(w in str(it.get("type") or "").lower() for w in ("sentiment", "rating"))
        ]
        v3_txt = f"v3截获(included {len(inc)}项, 情绪对象{len(sent)}个)"
        if sent:
            v3_txt += " 样例=" + json.dumps(sent[0], ensure_ascii=False)[:260]
    else:
        v3_txt = "v3未截获"

    raw = str(row.get("ssrSnippet") or "")
    parts = [p for p in raw.split(" ### ") if p]
    cands = [
        m.group(1).lower()
        for m in re.finditer(_SSR_RATING_PAT, raw.replace('\\"', '"'), flags=re.IGNORECASE)
    ]
    samples = "\n   ‖ ".join(p[150:420] for p in parts[:3])
    return v3_txt, len(parts), cands, samples


def parse_dataset_array(arr, symbol, schema_ver):
    if not isinstance(arr, list) or not arr:
        return [], "数据集暂无记录"
    valid_rows = [
        x for x in arr
        if isinstance(x, dict)
        and x.get("schema") == schema_ver
        and str(x.get("symbol") or "").upper() == symbol
    ]
    if not valid_rows:
        return [], f"非当前股票{schema_ver}记录"

    valid_rows.sort(key=lambda r: int(r.get("order", 999)))
    out, lines, details = [], [], []
    blocked_cnt = 0
    shown_rated = 0
    shown_unrated = 0

    for idx, row in enumerate(valid_rows):
        if row.get("blocked"):
            blocked_cnt += 1

        src = ""
        rk = extract_rating_from_single_article_v3(row.get("capturedV3"), symbol)
        if rk:
            src = "v3"
        elif row.get("ssrSnippet"):
            rk = extract_rating_from_ssr_snippet(row.get("ssrSnippet"))
            if rk:
                src = "ssr"

        v3_txt, n_parts, cands, samples = _row_debug(row)
        title = str(row.get("title_en") or "")[:50]
        lines.append(
            f"#{idx + 1} 评级={rk or '无'}{'(' + src + ')' if src else ''} | {v3_txt} | "
            f"ssr片段{n_parts}个, 候选={cands} | {title}"
        )

        # 原始片段：打印 1 篇有评级的 + 前 2 篇没评级的
        show = False
        if rk and shown_rated < 1:
            shown_rated += 1
            show = True
        elif not rk and shown_unrated < 2:
            shown_unrated += 1
            show = True
        if show:
            head_txt = str(row.get("headText") or "")[:150]
            details.append(
                f"—— #{idx + 1} 原始内容 ——\n头部: {head_txt}\nssr: {samples or '(空)'}"
            )

        out.append({
            "title_en": row.get("title_en") or "",
            "date": row.get("date") or "",
            "author": row.get("author") or "Seeking Alpha Analyst",
            "rating_key": rk,
        })

    ratings_preview = [x.get("rating_key") for x in out[:5]]
    diag = (
        f"前5评级={ratings_preview}, 被反爬拦截={blocked_cnt}/{len(valid_rows)}篇\n"
        + "\n".join(lines) + "\n" + "\n".join(details)
    )
    return out, diag





def _resolve_run(token, symbol, schema_ver, run_id, ds_id, max_wait):
    """
    等待任务并读取数据集（没跑完也读已完成的部分，用于诊断）。
    返回 (带评级的文章列表或None, 说明, 任务是否已结束)。
    """
    status, ds2 = wait_for_run(token, run_id, max_wait)
    ds_id = ds2 or ds_id
    finished = status in SA_TERMINAL
    arr = fetch_dataset_items(token, ds_id) if ds_id else []
    cand, diag = parse_dataset_array(arr, symbol, schema_ver)
    note = f"run={str(run_id)[:8]} 状态={status}, 已出结果{len(arr)}篇 | {diag}"
    if finished and cand and any(a.get("rating_key") for a in cand):
        return cand, note, True
    return None, note, finished


@st.cache_data(ttl=21600, show_spinner=False)
def _load_sa_rated(symbol, schema_ver):
    """只有成功拿到至少一个评级才会被缓存 6 小时；否则抛异常，不缓存。"""
    token = get_apify_token()
    if not token:
        raise SARatingUnavailable("未配置APIFY_API_TOKEN")
    reg = _sa_state_registry()
    pkey = f"pending:{schema_ver}:{symbol}"

    # 1. 上次没等完的任务：继续检查同一个任务，不重新启动
    pending = reg.get(pkey)
    if pending:
        if time.time() - pending["started"] > SA_PENDING_MAX_SECS:
            reg.pop(pkey, None)
        else:
            cand, note, finished = _resolve_run(
                token, symbol, schema_ver,
                pending["run_id"], pending.get("ds_id"), SA_RECHECK_WAIT_SECS,
            )
            if cand:
                reg.pop(pkey, None)
                return finalize_articles(cand), note
            if not finished:
                raise SARatingPending(note)
            reg.pop(pkey, None)
            raise SARatingUnavailable(note)

    # 2. 复用最近 6 小时内、同股票、且确实带评级的数据集
    prev_note = ""
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
                    age_h = (
                        pd.Timestamp.now("UTC") - pd.to_datetime(started_at, utc=True)
                    ).total_seconds() / 3600.0
                    if age_h > 6:
                        fresh = False
                if run_info.get("status") in ("SUCCEEDED", "TIMED-OUT") and ds_id and fresh:
                    cand, diag = parse_dataset_array(
                        fetch_dataset_items(token, ds_id), symbol, schema_ver
                    )
                    if cand and any(a.get("rating_key") for a in cand):
                        return finalize_articles(cand), f"命中{schema_ver}缓存({ds_id[:8]}) | {diag}"
                    if cand and not prev_note:
                        prev_note = f" | 此前一次运行({ds_id[:8]}): {diag}"
    except Exception:
        pass

    # 3. 启动新任务，先登记为“进行中”，再限时等待
    run_id, ds_id, start_note = start_puppeteer_run(token, symbol, schema_ver)
    if not run_id:
        raise SARatingUnavailable(start_note + prev_note)
    reg[pkey] = {"run_id": run_id, "ds_id": ds_id, "started": time.time()}

    cand, note, finished = _resolve_run(
        token, symbol, schema_ver, run_id, ds_id, SA_FIRST_WAIT_SECS
    )
    if cand:
        reg.pop(pkey, None)
        return finalize_articles(cand), note
    if not finished:
        raise SARatingPending(note + prev_note)
    reg.pop(pkey, None)
    raise SARatingUnavailable(note + prev_note)


@st.cache_data(ttl=900, show_spinner=False)
def _load_sa_xml_only(symbol):
    """保底通道：仅文章列表、无评级，只缓存 15 分钟。"""
    try:
        return finalize_articles(fetch_sa_xml_articles(symbol, 10))
    except Exception:
        return []


def load_seeking_alpha_feed(symbol, has_token):
    reg = _sa_state_registry()
    note = ""
    if has_token:
        key = f"{CACHE_SCHEMA_VER}:{symbol}"
        last = reg.get(key)
        has_pending = f"pending:{key}" in reg
        if has_pending or not last or time.time() - last[0] > SA_FAIL_RETRY_SECS:
            try:
                result = _load_sa_rated(symbol, CACHE_SCHEMA_VER)
                reg.pop(key, None)
                return result
            except SARatingPending as e:
                note = f"评级抓取仍在进行中，稍后刷新页面会继续检查同一任务: {e} | "
            except SARatingUnavailable as e:
                reg[key] = (time.time(), str(e))
            except Exception as e:
                reg[key] = (time.time(), f"异常:{str(e)[:80]}")
        if not note and key in reg:
            fail_ts, fail_msg = reg[key]
            wait_min = max(0, int((SA_FAIL_RETRY_SECS - (time.time() - fail_ts)) / 60))
            note = f"评级抓取失败（约{wait_min}分钟后自动重试）: {fail_msg} | "

    articles = _load_sa_xml_only(symbol)
    note += "回退官方XML流（无评级）" if articles else "官方XML流也未取到文章"
    return articles, note



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
                    height=340,
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
                f"正在打开 {ticker} 最新 8 篇分析原文同步官网评级（首次约 30~90 秒，成功后 6 小时秒开）..."
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

# 诊断信息：始终显示（个股 / ETF / PE 加载失败时都能看到）
if sa_debug_msg:
    with st.expander("📡 Seeking Alpha 数据通道状态", expanded=True):
        st.code(sa_debug_msg, language=None)


st.caption("数据来源：Yahoo Finance、SEC EDGAR、Seeking Alpha，仅供参考，不构成投资建议。")
