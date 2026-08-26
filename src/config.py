"""Runtime configuration shared by local and Streamlit Cloud deployments."""

from __future__ import annotations

import os


def get_secret(name: str) -> str | None:
    """Read a secret from environment variables or Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:
        return None
    return str(value) if value else None
