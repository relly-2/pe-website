import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import requests

# 请把邮箱改成你自己的（SEC 要求）
HEADERS = {"User-Agent": "PE-Website aihuaxiawenhua@gmail.com"}

st.set_page_config(page_title="美股历史市盈率", layout="wide")
st.title("📈 美股历史市盈率走势")

ticker = st.text_input("输入股票代码（如 AAPL、MSFT、NVDA）", "AAPL").upper().strip()
years = st.selectbox("时间范围（年）", [1, 3, 5, 10], index=3)


def to_ns(s):
    return pd.to_datetime(s).astype("datetime64[ns]")


@st.cache_data(ttl=86400)
def get_cik(symbol):
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers=HEADERS, timeout=30)
    r.raise_for_status()
    for item in r.json().values():
        if item["ticker"].upper() == symbol:
            return int(item["cik_str"])
    return None


@st.cache_data(ttl=86400)
def get_sec_facts(symbol):
    cik = get_cik(symbol)
    if cik is None:
        return None
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None
    return r.json().get("facts", {}).get("us-gaap", {})


def build_ttm_eps(facts, splits_series):
    """
    从 SEC 数据提取单季 EPS 并合成 TTM EPS：
    1. 取最新披露口径（SEC 历史对比列通常已按后续拆股重述）
    2. 对未被后续财报重述的早期数据，按财报披露日(filed)补做拆股调整
    3. 支持用 6个月/9个月/全年累计值 减去前期累计值，精准推算单季 EPS（彻底解决 Q4 缺失和 52/53 周日历问题）
    """
    rows = None
    for concept in ["EarningsPerShareDiluted", "EarningsPerShareBasic"]:
        if concept in facts and "USD/shares" in facts[concept]["units"]:
            rows = facts[concept]["units"]["USD/shares"]
            break
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["start", "end", "filed", "val"])
    # 只保留季报和年报
    df = df[df["form"].isin(["10-Q", "10-K", "10-Q/A", "10-K/A"])].copy()
    if df.empty:
        return None

    df["start"] = to_ns(df["start"])
    df["end"] = to_ns(df["end"])
    df["filed"] = to_ns(df["filed"])
    df["val"] = df["val"].astype(float)
    df["dur"] = (df["end"] - df["start"]).dt.days

    # 每段期间：记录【最早披露日】（用于历史回放防未来函数）和【最新报告值】（同口径最干净）
    first_filed = df.groupby(["start", "end"])["filed"].min().rename("first_filed")
    latest = (df.sort_values("filed")
                .groupby(["start", "end"], as_index=False)
                .last()
                .merge(first_filed, on=["start", "end"]))

    # 按【最新那份财报的披露日】做拆股修正：如果最新财报是在拆股前发的，才需要除以拆股倍数
    def adj_split(row):
        f = 1.0
        for sd, ratio in splits_series.items():
            # 拆股发生在最新财报披露日之后，说明该数值尚未按这次拆股重述
            if sd > row["filed"]:
                f *= float(ratio)
        return row["val"] / f

    latest["val_adj"] = latest.apply(adj_split, axis=1)

    # 1) 直接的单季数据（约 65 ~ 115 天，兼容 52/53 周财年如 Costco 的 12周/16周季度）
    q_direct = latest[latest["dur"].between(65, 115)].copy()
    q_map = {}
    for _, r in q_direct.iterrows():
        q_map[r["end"]] = {
            "start": r["start"],
            "end": r["end"],
            "val": r["val_adj"],
            "filed": r["first_filed"],
        }

    # 2) 用累计数据（半年 ~180天、三季 ~270天、全年 ~365天）推算缺失的单季（尤其是 Q4）
    cum_df = latest[latest["dur"].between(165, 385)].sort_values("dur")
    for _, yr in cum_df.iterrows():
        # 如果这个期末已经有单季值了，跳过
        if yr["end"] in q_map:
            continue
        # 找同一个财年起点(start 误差在 7 天内)且包含在里面的已知单季
        inside = [
            v for v in q_map.values()
            if v["start"] >= yr["start"] - pd.Timedelta(days=7)
            and v["end"] < yr["end"] - pd.Timedelta(days=30)
        ]
        inside_days = sum((v["end"] - v["start"]).days for v in inside)
        rem_days = yr["dur"] - inside_days
        # 剩余天数刚好是一个季度（约 65~120 天），就能精准相减得出该季 EPS
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

    # 合并距离极近的重复期末（兼容个别公司改财年日）
    cleaned = []
    for _, r in qdf.iterrows():
        if cleaned and (r["end"] - cleaned[-1]["end"]).days < 20:
            cleaned[-1] = r.to_dict()
        else:
            cleaned.append(r.to_dict())
    qdf = pd.DataFrame(cleaned)

    # 连续 4 个季度滚动求和得到 TTM EPS
    ttm_rows = []
    for i in range(3, len(qdf)):
        w = qdf.iloc[i - 3:i + 1]
        # 4个季度的期末跨度大约是 3 个季度间隔（约 250 ~ 310 天）
        span = (w["end"].iloc[-1] - w["end"].iloc[0]).days
        if 240 <= span <= 320:
            ttm_rows.append({
                "period_end": w["end"].iloc[-1],
                "filed": to_ns(w["filed"].max()),
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
def load_pe(symbol, years):
    facts = get_sec_facts(symbol)
    if not facts:
        return None, None

    t = yf.Ticker(symbol)
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)
    # 多往前取半年股价，方便对齐早期财报
    fetch_start = start - pd.DateOffset(months=6)

    hist = t.history(start=fetch_start.strftime("%Y-%m-%d"), auto_adjust=False)
    if hist.empty:
        return None, None

    df = hist[["Close"]].reset_index()
    df.columns = ["date", "close"]
    d = pd.to_datetime(df["date"])
    if d.dt.tz is not None:
        d = d.dt.tz_localize(None)
    df["date"] = d.astype("datetime64[ns]")
    df["close"] = df["close"].astype(float)

    # 获取拆股历史
    sp = pd.Series(dtype=float)
    try:
        s = t.splits
        if s is not None and len(s) > 0:
            sp = s.copy()
            idx = pd.to_datetime(sp.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            sp.index = idx.astype("datetime64[ns]")
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
    # EPS <= 0 时记为 NaN（亏损期无正向 PE）
    df["pe"] = (df["close"] / df["ttm"]).where(df["ttm"] > 0)
    df = df[df["date"] >= start].reset_index(drop=True)
    return df, qdf


if ticker:
    with st.spinner("正在获取并计算 10 年数据..."):
        df, qdf = load_pe(ticker, years)

    if df is None or df["pe"].dropna().empty:
        st.error("没有找到该股票的数据，或该股票没有足够的正 EPS 记录。请检查代码，或确认邮箱已修改。")
    else:
        valid = df.dropna(subset=["pe"])
        median = valid["pe"].median()
        last_valid = valid.iloc[-1]
        current_pe = last_valid["pe"]
        percentile = (valid["pe"] < current_pe).mean() * 100

        col1, col2, col3 = st.columns(3)
        # 如果最新交易日处于亏损状态，提示最新为负收益
        if pd.isna(df["pe"].iloc[-1]):
            col1.metric("当前 PE", "亏损 (N/A)")
        else:
            col1.metric("当前 PE", f"{current_pe:.1f}")
        col2.metric("历史中位数", f"{median:.1f}")
        col3.metric("当前 PE 历史分位", f"{percentile:.0f}%")

        # 注意：这里传入完整的 df（保留 NaN），并设置 connectgaps=False
        # 这样如果真遇到亏损年份，曲线会留白断开，而不会画一条斜线误导人
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["pe"],
            mode="lines",
            name="PE (TTM)",
            connectgaps=False,
        ))
        fig.add_hline(y=median, line_dash="dash", annotation_text=f"中位数 {median:.1f}")
        fig.update_layout(
            height=500,
            yaxis_title="市盈率 (PE)",
            xaxis_title="日期",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        # 检查期间是否有因为亏损导致的正常断档，给用户清晰提示
        loss_days = df["ttm"].notna() & (df["ttm"] <= 0)
        if loss_days.any():
            st.info("💡 图表中空白断开的区间代表该公司当时处于亏损状态（TTM 每股收益 ≤ 0），市盈率无意义。")

        with st.expander("🔍 查看底层单季 EPS 明细（用于核对数据）"):
            show_q = qdf.sort_values("end", ascending=False).copy()
            show_q["end"] = show_q["end"].dt.strftime("%Y-%m-%d")
            show_q["filed"] = show_q["filed"].dt.strftime("%Y-%m-%d")
            show_q["val"] = show_q["val"].round(4)
            st.dataframe(
                show_q[["end", "filed", "val"]].rename(columns={
                    "end": "财报期末",
                    "filed": "首次披露日",
                    "val": "拆股调整后单季EPS($)",
                }),
                use_container_width=True,
            )

        st.caption("数据来源：Yahoo Finance（股价）、SEC EDGAR（EPS），仅供参考，不构成投资建议。")
