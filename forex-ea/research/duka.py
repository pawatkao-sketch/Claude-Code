"""Load Dukascopy hourly BID candles (monthly .bi5 files) into pandas."""
import glob
import lzma
import os
import struct

import numpy as np
import pandas as pd


def point(pair):
    return 1e3 if pair.endswith("JPY") or pair[:3] in ("XAU", "XAG") else 1e5


def load_hourly(folder, pair):
    frames = []
    for path in sorted(glob.glob(os.path.join(folder, pair, "*_BID.bi5"))):
        if os.path.getsize(path) == 0:
            continue
        y, m = os.path.basename(path).split("_")[:2]
        raw = lzma.decompress(open(path, "rb").read())
        a = np.frombuffer(raw, dtype=">i4").reshape(-1, 6)
        t0 = pd.Timestamp(year=int(y), month=int(m) + 1, day=1)
        vol = np.frombuffer(raw, dtype=">f4").reshape(-1, 6)[:, 5]
        df = pd.DataFrame({"open": a[:, 1], "close": a[:, 2], "low": a[:, 3], "high": a[:, 4]},
                          dtype=float) / point(pair)
        df["volume"] = vol
        df.index = t0 + pd.to_timedelta(a[:, 0], unit="s")
        frames.append(df)
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[df["volume"] > 0]          # drop weekend / holiday filler bars
