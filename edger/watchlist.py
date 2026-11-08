"""Watchlist kept in the viewer's browser (localStorage), so it survives app restarts and
works per phone without any account or server-side database.

Streamlit cannot read browser storage directly; ``streamlit_js_eval`` runs a JS snippet in
the page and returns its value on a later rerun. Until it answers, the list is empty.
"""
from __future__ import annotations

import json

import streamlit as st

STORAGE_KEY = "edger.watchlist"
MAX_ITEMS = 20
_STATE = "watchlist"
_DIRTY = "watchlist_dirty"
_LOADED = "watchlist_loaded"


def _js(expr: str, key: str):
    try:
        from streamlit_js_eval import streamlit_js_eval
    except ImportError:  # optional dependency missing: watchlist lives for the session only
        return None
    return streamlit_js_eval(js_expressions=expr, key=key)


def init() -> None:
    """Ask the browser for the saved list. Call exactly once per run, near the top."""
    if st.session_state.get(_LOADED):
        return
    raw = _js(f"localStorage.getItem('{STORAGE_KEY}') || '[]'", key="wl_load")
    if raw is None:  # browser has not answered yet; it triggers a rerun when it does
        return
    try:
        items = [str(t).upper() for t in json.loads(raw) if str(t).strip()]
    except (TypeError, ValueError):
        items = []
    st.session_state[_LOADED] = True
    pending = st.session_state.get(_STATE, [])  # added before the browser answered
    st.session_state[_STATE] = list(dict.fromkeys(items + pending))[:MAX_ITEMS]
    if pending:
        st.session_state[_DIRTY] = True


def load() -> list[str]:
    return st.session_state.get(_STATE, [])


def _set(items: list[str]) -> None:
    st.session_state[_STATE] = list(dict.fromkeys(items))[:MAX_ITEMS]
    st.session_state[_DIRTY] = True


def add(ticker: str) -> None:
    _set([*load(), ticker.upper()])


def remove(ticker: str) -> None:
    _set([t for t in load() if t != ticker.upper()])


def toggle(ticker: str) -> None:
    (remove if ticker.upper() in load() else add)(ticker)


def sync() -> None:
    """Write pending changes to the browser. Call once near the end of every run."""
    if not st.session_state.get(_DIRTY):
        return
    payload = json.dumps(st.session_state.get(_STATE, []))
    _js(f"localStorage.setItem('{STORAGE_KEY}', {json.dumps(payload)})",
        key=f"wl_save_{abs(hash(payload))}")
    st.session_state[_DIRTY] = False
