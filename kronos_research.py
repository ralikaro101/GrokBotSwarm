"""Optional Kronos M5 forecast adapter."""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

import mt5_client

_predictor = None


def mode():
    configured = os.getenv("SWARM_KRONOS_MODE", "").strip().lower()
    if configured in {"off", "shadow", "gate"}:
        return configured
    return "shadow" if os.getenv("SWARM_KRONOS_SHADOW", "off").strip().lower() == "on" else "off"


def enabled():
    return mode() != "off"


def _load_predictor():
    global _predictor
    if _predictor is not None:
        return _predictor
    home = Path(os.getenv("KRONOS_HOME", "")).expanduser()
    if not home.is_dir():
        raise RuntimeError("KRONOS_HOME is not a valid Kronos checkout.")
    sys.path.insert(0, str(home))
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer
    except ImportError as exc:
        raise RuntimeError(f"Could not import Kronos: {exc}") from exc
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    _predictor = KronosPredictor(model, tokenizer, max_context=512)
    return _predictor


def forecast(symbol):
    """Return one M5 close-direction forecast, or raise a clear setup error."""
    if not enabled():
        return None
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Install Kronos dependencies on the VPS first.") from exc

    candles = mt5_client.candles(symbol, 400, timeframe="M5")
    frame = pd.DataFrame(candles)
    timestamps = pd.to_datetime(frame.pop("time"), unit="s", utc=True)
    predictor = _load_predictor()
    future = pd.Series([timestamps.iloc[-1] + timedelta(minutes=5)])
    prediction = predictor.predict(
        df=frame[["open", "high", "low", "close", "volume"]],
        x_timestamp=timestamps,
        y_timestamp=future,
        pred_len=1,
        T=1.0,
        top_p=0.9,
        sample_count=1,
        verbose=False,
    )
    last_close = float(frame["close"].iloc[-1])
    predicted_close = float(prediction["close"].iloc[0])
    direction = "buy" if predicted_close > last_close else "sell"
    return {
        "direction": direction,
        "last_close": last_close,
        "predicted_close": predicted_close,
        "change": predicted_close - last_close,
    }
