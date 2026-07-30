# External Forex Research Data

`Forex_sample_dataset.csv` is a research-only copy of **Forex Trading Dataset
with EMA, RSI & ATR (2025)** by Fijabi J. Adekunle:

https://www.kaggle.com/datasets/jeleeladekunlefijabi/forex-trading-dataset-with-ema-rsi-and-atr

- Kaggle dataset version: `1`
- Dataset license: `CC BY-SA 4.0`
- Source SHA-256:
  `def896b19b80b36fdd154a0de1ef001c05fd774769d5896a414959010896428c`
- Imported rows: `926`
- Pairs: `EUR/USD`, `GBP/USD`, `USD/JPY`
- Source timeframe: daily

BLUM does not use the source's precomputed EMA, RSI, ATR, support, resistance,
or labels as truth. It recalculates trailing indicators from OHLC, creates
outcomes only after each decision timestamp, applies estimated transaction
costs, and assigns these examples a reduced training weight. The source cannot
directly authorize a paper trade or establish an alpha claim.

The dataset is redistributed under its stated
[CC BY-SA 4.0 license](https://creativecommons.org/licenses/by-sa/4.0/).
