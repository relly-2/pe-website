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
def get_eps_quarterly(symbol):
    """从 SEC 获取每个季度的 EPS（单季值）"""
    cik = get_cik(symbol)
    if cik is None:
        return None

    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return None
    facts = r.json().get("facts", {}).get("us-gaap", {})

    rows = None
    for concept in ["EarningsPerShareDiluted", "EarningsPerShareBasic"]:
        if concept in facts and "USD/shares" in facts[concept]["units"]:
            rows = facts[concept]["units"]["USD/shares"]
            break
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["start"])
    df["start"] = to_ns(df["start"])
    df["end"] = to_ns(df["end"])
    df["filed"] = to_ns(df["filed"])
    df["dur"] = (df["end"] - df["start"]).dt.days

    # 10-Q 中约 3 个月的单季数据
    q = df[df["form"].str.startswith("10-Q") & df["dur"].between(60, 100)]
    q = (q.sort_values("filed")
          .groupby(["start", "end"], as_index=False)
          .agg(val=("val", "first"), filed=("filed", "min")))

    # 10-K 中约 12 个月的全年数据
    a = df[df["form"].str.startswith("10-K") & df["dur"].between(350, 380)]
    a = (a.sort_values("filed")
          .groupby(["start", "end"], as_index=False)
          .agg(val=("val", "first"), filed=("filed", "min")))

    # 第四季度 = 全年 - 前三季度
    q4_rows = []
    for _, yr in a.iterrows():
        inside = q[(q["start"] >= yr["start"]) & (q["end"] <= yr["end"])]
        if len(inside) == 3:
            q4_rows.append({
                "end": yr["end"],
                "val": yr["val"] - inside["val"].sum(),
                "filed": yr["filed"],
            })

    q4 = pd.DataFrame(q4_rows, columns=["end", "val", "filed"])
    qdf = pd.concat([q[["end", "val", "filed"]], q4], ignore_index=True)
    qdf["end"] = to_ns(qdf["end"])
    qdf["filed"] = to_ns(qdf["filed"])
    qdf["val"] = qdf["val"].astype(float)
    qdf = qdf.sort_values(["end", "filed"]).drop_duplicates("end").reset_index(drop=True)
    return qdf


def split_factor(d, sp):
    """计算某日期之后发生的拆股倍数的乘积"""
    f = 1.0
    for sd, ratio in sp.items():
        if sd > d:
            f *= float(ratio)
    return f


@st.cache_data(ttl=86400)
def load_pe(symbol, years):
    qdf = get_eps_quarterly(symbol)
    if qdf is None or qdf.empty:
        return None

    t = yf.Ticker(symbol)
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)

    # 股价：auto_adjust=False 时 Close 已做拆股调整，未做分红调整
    hist = t.history(start=start.strftime("%Y-%m-%d"), auto_adjust=False)
    if hist.empty:
        return None
    df = hist[["Close"]].reset_index()
    df.columns = ["date", "close"]
    d = pd.to_datetime(df["date"])
    if d.dt.tz is not None:
        d = d.dt.tz_localize(None)
    df["date"] = d.astype("datetime64[ns]")
    df["close"] = df["close"].astype(float)

    # 拆股信息，用于把 EPS 调整到与股价相同的口径
    sp = pd.Series(dtype=float)
    try:
        s = t.splits
        if s is not None and len(s) > 0:
            sp = s.copy()
            idx = pd.to_datetime(sp.index)
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            sp.index = idx
    except Exception:
        pass

    # 先调整每个季度的 EPS，再求和得到 TTM
    qdf["val"] = qdf.apply(lambda r: r["val"] / split_factor(r["end"], sp), axis=1)

    rows = []
    for i in range(3, len(qdf)):
        w = qdf.iloc[i - 3:i + 1]
        if (w["end"].iloc[-1] - w["end"].iloc[0]).days > 330:
            continue
        rows.append({
            "filed": w["filed"].max(),
            "ttm": w["val"].sum(),
        })
    if not rows:
        return None

    ttm = pd.DataFrame(rows)
    ttm["filed"] = to_ns(ttm["filed"])
    ttm["ttm"] = ttm["ttm"].astype(float)
    ttm = ttm.sort_values("filed").reset_index(drop=True)

    df = pd.merge_asof(
        df.sort_values("date").reset_index(drop=True),
        ttm,
        left_on="date", right_on="filed", direction="backward",
    )
    df["pe"] = (df["close"] / df["ttm"]).where(df["ttm"] > 0)
    return df[df["date"] >= start].reset_index(drop=True)


if ticker:
    with st.spinner("正在获取数据（10年数据首次加载可能需要 30 秒左右）..."):
        df = load_pe(ticker, years)

    if df is None or df["pe"].dropna().empty:
        st.error("没有找到该股票的数据，或该股票没有足够的正 EPS 记录。请检查代码，或确认 SEC 访问邮箱已设置。")
    else:
        valid = df.dropna(subset=["pe"])
        median = valid["pe"].median()
        current = valid["pe"].iloc[-1]
        percentile = (valid["pe"] < current).mean() * 100

        col1, col2, col3 = st.columns(3)
        col1.metric("当前 PE", f"{current:.1f}")
        col2.metric("历史中位数", f"{median:.1f}")
        col3.metric("当前 PE 历史分位", f"{percentile:.0f}%")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=valid["date"], y=valid["pe"], mode="lines", name="PE"))
        fig.add_hline(y=median, line_dash="dash", annotation_text="中位数")
        fig.update_layout(height=500, yaxis_title="市盈率 (PE)", xaxis_title="日期")
        st.plotly_chart(fig, use_container_width=True)

        st.caption("数据来源：Yahoo Finance（股价）、SEC EDGAR（EPS），仅供参考，不构成投资建议。")
