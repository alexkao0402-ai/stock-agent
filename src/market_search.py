"""One shared ticker-search form, independent of strategy account state."""
from src.market_intelligence import valid_symbol


def render_market_search():
    import streamlit as st

    if "market_query" not in st.session_state:
        st.session_state["market_query"] = st.session_state.get("market_symbol", "")
    with st.form("market_search", clear_on_submit=False):
        search, action = st.columns([5, 1], vertical_alignment="bottom")
        query = search.text_input("Stock ticker", key="market_query", placeholder="AAPL, GOOGL, NVDA or another ticker")
        with action:
            submitted = st.form_submit_button("Search", type="primary", width="stretch")
    if submitted:
        symbol = query.strip().upper()
        if not valid_symbol(symbol):
            st.session_state.pop("market_symbol", None)
            st.warning("Enter a valid ticker, for example AAPL, GOOGL, NVDA or BRK-B.")
            return None
        st.session_state["market_symbol"] = symbol
    symbol = st.session_state.get("market_symbol")
    if not symbol:
        st.info("Enter a ticker above, then press Search or Enter.")
    return symbol
