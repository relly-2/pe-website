import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="美股历史市盈率", layout="wide")
st.title("📈 美股历史市盈率走势")

ticker = st.text_input("输入股票代码（如 AAPL、MSFT、NVDA）", "AAPL").upper().strip()
years = st.selectbox("时间范围（年）", [1, 2, 3, 5], index=1)

@st.cache_data(ttl=86400)
def load_pe(symbol, years):
    t = yf.Ticker(symbol)

    # 多取一年股价，用于计算前期的 TTM EPS
    hist = t.history(period=f"{years + 1}y")[["Close"]]
    if hist.empty:
        return None
    hist.index = hist.index.tz_localize(None)
    df = hist.reset_index()
    df.columns = ["date", "close"]
    # 统一成 datetime64[ns]，避免与财报日期类型不一致
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["close"] = df["close"].astype(float)

    # 获取季度每股稀释收益
    inc = t.quarterly_income_stmt
    if inc is None or inc.empty or "Diluted EPS" not in inc.index:
        return None
    eps = inc.loc["Diluted EPS"].dropna().sort_index()
    ttm = eps.astype(float).rolling(4).sum().dropna()
    if ttm.empty:
        return None

    # 财报通常在季度结束后约 45 天发布，用它作为"可用日期"
    filed_dates = (pd.to_datetime(ttm.index) + pd.Timedelta(days=45)).astype("datetime64[ns]")
    eps_df = pd.DataFrame({
        "filed": filed_dates,
        "ttm": ttm.values.astype(float),
    }).sort_values("filed").reset_index(drop=True)

    # 每个交易日匹配"当时已经公布的最新 TTM EPS"
    df = pd.merge_asof(
        df.sort_values("date").reset_index(drop=True),
        eps_df,
        left_on="date", right_on="filed", direction="backward",
    )
    df["pe"] = (df["close"] / df["ttm"]).where(df["ttm"] > 0)

    # 只保留用户选择的时间段
    start = pd.Timestamp.today().normalize() - pd.DateOffset(years=years)
    return df[df["date"] >= start]

if ticker:
    with st.spinner("正在获取数据..."):
        df = load_pe(ticker, years)

    if df is None or df["pe"].dropna().empty:
        st.error("没有找到该股票的数据，或该股票最近没有正的每股收益。请检查代码。")
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

        st.caption("数据来源：Yahoo Finance，仅供参考，不构成投资建议。")
