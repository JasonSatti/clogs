"""Shared test utilities."""
import re


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)
