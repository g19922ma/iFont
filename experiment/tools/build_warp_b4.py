#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
群B（検証フェーズ）の warp 表を作り直す v4 — 曲線の推定方法を入れ替える
=======================================================================
build_warp_b3.py の**曲線の推定だけ**を差し替えた版。
データの絞り込み・組み合わせの写し方（字ごとの窓・線形）・対照の作り方は b3 のまま。

■ なぜ作り直すか
   論文 3.3 節は「関数形をあらかじめ決めずに単調性の制約を課した回帰」で q̂A・q̂V を
   推定すると書いてある。理由も書いてある——**双方をロジスティックに当てはめてから
   逆引きすると、得られる変換はほぼ一次変換に潰れる**からである。
   これは比喩ではなく恒等式で、γ と λ が両側で等しいなら

       V̂⁻¹(Â(t)) = μV + σV·(t − μA)/σA

   と、開始時刻の平行移動と速度の定数倍そのものになる。
   ところが実装（build_warp_b.py 系）はロジスティック当てはめから逆引きしていた。
   実際、v3 の表で「提案」と「対照2（一次変換）」の平均差は
   うすい 3.40pt・点が増える 7.11pt しかない（19 コマ×8字の平均）。
   **提案手法が対照条件と実質同じものになっていた。**

■ v4 で比べる 5 とおりの推定
   logistic         現行と同じ。γ 固定・λ 自由の 3 母数ロジスティック（比較の基準）
   logistic_clamped 同じ当てはめだが、測った範囲の外へ伸ばさない（外挿の切り分け用）
   isotonic         単調回帰。関数形を置かず、単調性だけを制約にした最尤（重み付き PAVA）
   selected_bestcv  字ごと・方式ごとに 6 候補から形を選ぶ（交差確認の逸脱度が最小）
   selected_1se     同じ手続きで、1SE 則（最小から1標準誤差以内でいちばん単純な形）

■ 比べ方（物差しを3つに分ける。1つでは判断を誤る）
   ① 進み具合の空間 … 提案と対照2の平均差 pt。方式ごとに目盛りの意味が違うので単独では読めない
   ② 正答率の空間 … 参加者が受け取る「読める確率」の差 pt。共通の参照曲線で測る
   ③ 目標軌跡の再現 … 逆引きした s を共通の参照曲線に通し、聴覚の目標との RMSE。
      ★ **提案が対照2よりどれだけ目標に近いか（gain_over_b2）が仮説そのもの**である。
        ここが 0 以下なら、その転写は対照条件と区別できない（または悪い）。
   ④ 一次変換への潰れ具合 … 提案の軌跡を時間の直線で近似したときの残差／可動域
   ⑤ 分解能 … 提案の道の上に出る「別々の絵」の枚数と、7つの打ち切り時点が何枚に分かれるか
   ⚠ ②③④は**その字の最大打ち切り時刻までの窓**で測る。それより後は参加者に見えない。

■ 転写に使う方式（2026-08-28 丸山判断）
   主軸 … ぼやけ(blur) と 端から(wipe)、およびその組み合わせ **ぼやけ×端から（未実装）**
   参考 … うすい(fade)・点が増える(reveal) とその組み合わせ（落とす判断の根拠を数字で残す）

■ 平滑化の程度をどう決めたか（isotonic）
   PAVA そのものには平滑化の目盛りが無い。単調性が要求する分だけならされる。
   ただし出力は階段になり、平らな段は逆引きできない（跳ねる）。
   そこで **参加者単位のブートストラップで PAVA を袋詰め（bagging）** する。
   袋詰めは
     ・平滑化の強さを人が選ばない（データ自身のばらつきが決める。
       試行が増えれば自動的に平滑化が弱くなる）
     ・単調関数の平均なので単調性が壊れない
     ・平らな段がほぐれて逆引きが一意になる
   の 3 点を満たす。**調整つまみはゼロ**（袋の数 B は収束の問題で、当てはめの自由度ではない）。
   B を振ったときの動きは smoothing_sensitivity.csv に出す。

■ 水準と水準のあいだ・端の外挿
   水準のあいだ … 対数 x での線形補間（区間ごとにべき乗）。逆関数は区間内で解析的に解ける。
                   較正のはしごは等比で置いてある（うすい 0.4→0.8→1.4→2.2→3.5→6→12%）ので、
                   設計が等間隔とみなした目盛りでつなぐ。--interp linear で生の x 線形も出せる。
   端の外 …… **外挿しない**。測った範囲の外は、いちばん外側の測定値で一定とする。
              聴覚は上端（字により 60〜125ms）より後がずっと一定になる。
              視覚は全方式が 100% を測っているので上端の外挿は起きない。
              下端（うすい 0.4% など）より下も一定。逆引きが下端を割ったら s=0、
              上端を超えたら s=100 に丸め、回数を build_log に残す。
   ⚠ 現行のロジスティック版は外挿する（測っていない範囲でも曲線が伸びる）。
     差が「推定方法」から来たのか「外挿の扱い」から来たのかを切り分けるため、
     ロジスティックにも同じ丸めをかけた版（logistic_clamped）を並べて出す。

■ 形を選ぶ手続き（selected）— 結果を見る前に決めたもの
   候補（6 つだけ。増やすと「たまたま合う形」を選ぶ）
     定数     p = c                                     母数1
     直線     p = clip(a + b·x, γ, 1),  b ≥ 0            母数2
     階段     p = c0 (x<θ) / c1 (x≥θ), c1 ≥ c0          母数3  θ は隣り合う水準の幾何平均のみ
     指数飽和 p = c + (λ−c)(1 − exp(−x/τ))              母数3  床 c が自由（回答の偏りを吸収）
     ロジスティック p = γ + (λ−γ)·logistic((x−μ)/σ)     母数3  床は当て推量に固定
     単調回帰 袋詰め PAVA                                母数は非母数
   選び方
     参加者を 5 つに分ける（乱数の種は固定）→ 4/5 で当てはめ、残り 1/5 の試行で
     二項の逸脱度（−2·対数尤度）を測る → 5 回の平均が最小の候補を選ぶ。
     ただし **1SE 則**：最小から 1 標準誤差以内の候補があれば、
     そのうち**いちばん単純なもの**を採る（単純さの順序は上の並び順で固定）。
   単調性はどの候補も構造として持つ（b ≥ 0、c1 ≥ c0、σ > 0、τ > 0、PAVA）。
   逆関数はどの候補も解析的に書ける（定数・階段は一般化逆＝跳ぶ）。

出力（project/data_calib2_live/warp_v4/）
  transfer_warp_v4_<推定>.json       5 とおりの warp 表（<推定> は上の 5 つ）
  fit_curves.csv                     推定 × 字 × 方式の要約（λ・床・当てはめ逸脱度）
  model_selection.csv                候補ごとの交差確認の逸脱度（全40セル × 6候補）
  model_selection_table.csv          **どの字にどの形が選ばれたか**（最良CV / 1SE の両方）
  compare_estimators.csv             セルごとの ①〜⑤ 全部
  compare_summary.csv                主軸／参考／全体の要約（最重要の表）
  composite_resolution.csv           5〜95%の窓で作れる別々の絵の枚数（単体・組み合わせ）
  smoothing_sensitivity.csv          袋詰めの数 B と、袋詰めなし PAVA との差
  interp_sensitivity.csv             水準のあいだの補間（対数 x / 生の x）の差
  composite_window_v4.csv            組み合わせの窓（字ごとの s5/s95）
  build_log_v4.csv                   逆引きの丸め回数・s の範囲・跳ねの大きさ

本番ファイル（experiment/transfer_warp.json / transfer_config.js）には**書かない**。

使い方:
    python3 experiment/tools/build_warp_b4.py
    python3 experiment/tools/build_warp_b4.py --bag 400 --cv-folds 5
    node experiment/tools/check_warp_playback.js \
        project/data_calib2_live/warp_v4/transfer_warp_v4_selected.json
"""
import argparse
import io
import json
import math
import os
import sys
import warnings
import zlib

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_calib_full as acf  # noqa: E402

try:
    from scipy.optimize import minimize
    HAVE_SCIPY = True
except Exception:                                     # pragma: no cover
    HAVE_SCIPY = False

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARS = ["あ", "か", "が", "ぱ", "し", "つ", "ま", "ら"]
FAMS = ["fade", "reveal", "blur", "wipe"]
# 2026-08-28 丸山判断: 転写に使うのは **ぼやけ と 端から** の2つ。
#   うすい … 不透明度が256階調しかなく、効く区間 0.4〜2.6% では別々の絵が5〜14枚しか作れない
#   点が増える … 提示時間に弱い（密度 +8.8pt Holm後 p=0.007／同一水準17ms長で +8.3pt）
# うすい・点が増えるは**参考**として当てはめ・比較には残す（落とした判断の根拠を数字で残すため）。
FAMS_MAIN = ["blur", "wipe"]
FAMS_REF = ["fade", "reveal"]
# 組み合わせ。blur+wipe は未実装だが、今回の主役なので表を作って評価する。
PAIR_MAIN = ("blur", "wipe")
PAIRS = [("blur", "wipe"), ("fade", "blur"), ("fade", "wipe"),
         ("reveal", "blur"), ("reveal", "wipe")]
LAB = {"fade": "うすい", "reveal": "点が増える", "blur": "ぼやけ", "wipe": "端から"}

FRAME_MS = 1000.0 / 60.0
BASE_ANIM_MS = 300.0
DURATION_MS = 300.0
N_MAP = 101
L595 = math.log(19.0)          # ロジスティックの 5%点/95%点までの距離（σ 単位）
EPS = 1e-9

# 2026-08-27 に確定した前提 -------------------------------------------------
# ・2 バッチ（calib / calib2）は 1 つの較正実験として扱う
# ・ぼやけは WebKit の描画不具合があるので該当環境を除く
# ・視覚の当てはめは「点が増える」だけ 300ms に限定。他の 3 方式は 2 水準を束ねる
#   （速さの効果が有意なのは点が増えるだけ +8.8pt Holm後 p=0.007）
SPEED_BY_FAM = {"fade": None, "reveal": 300.0, "blur": None, "wipe": None}
WEBKIT_FAMILIES = {"blur"}

# 打ち切り時点（transfer_config.js visual.gates_ms と同じ。字ごとの実測時刻）
GATES_MS = {
    "_default": [20, 40, 60, 80, 110, 150, 220],
    "あ": [10, 20, 30, 35, 50, 65, 90], "か": [10, 20, 25, 35, 45, 60, 85],
    "が": [10, 20, 25, 35, 45, 60, 85], "ぱ": [10, 15, 25, 30, 40, 50, 70],
    "し": [10, 20, 30, 35, 40, 50, 60], "つ": [10, 20, 30, 35, 50, 65, 85],
    "ま": [10, 25, 35, 50, 65, 85, 125], "ら": [10, 25, 35, 50, 65, 85, 110],
}

# 候補の並び＝単純さの順序（1SE 則のタイブレークに使う。結果を見る前に固定）
CAND_ORDER = ["const", "linear", "step", "expsat", "logistic", "isotonic"]
CAND_JA = {"const": "定数", "linear": "直線", "step": "階段", "expsat": "指数飽和",
           "logistic": "ロジスティック", "isotonic": "単調回帰"}
CAND_NPAR = {"const": 1, "linear": 2, "step": 3, "expsat": 3, "logistic": 3,
             "isotonic": float("nan")}


# ===========================================================================
# 読み込み（b3 と同一）
# ===========================================================================
def load_trials(path):
    d = pd.read_csv(path, low_memory=False)
    for c in ["correct", "is_decoy", "is_filler", "is_test"]:
        if c in d.columns and d[c].dtype == object:
            d[c] = d[c].map({True: True, False: False, "TRUE": True, "FALSE": False,
                             "True": True, "False": False})
    ua = d["ua"].fillna("").astype(str)
    d["webkit"] = (
        ua.str.contains("iPhone|iPad|iPod", regex=True)
        | (ua.str.contains("Macintosh") & ua.str.contains("Safari")
           & ~ua.str.contains("Chrome|Chromium|Edg/|Firefox", regex=True)))
    n_test = int((d["is_test"] == True).sum())          # noqa: E712
    d = d[d["is_test"] != True].copy()                  # noqa: E712
    d["correct_i"] = d["correct"].astype(bool).astype(int)
    d["actual_s_pct"] = (pd.to_numeric(d["actual_s"], errors="coerce") * 100).round(4)
    d["base_anim_ms_i"] = pd.to_numeric(d["base_anim_ms"], errors="coerce")
    d["gate_ms_f"] = pd.to_numeric(d["gate_ms"], errors="coerce")
    print(f"読み込み: {os.path.relpath(path, ROOT)}  "
          f"全{len(d) + n_test}行（is_test {n_test}行を除外）")
    return d


def slices(d):
    v = d[d["modality"] == "transfer_visual"].copy()
    a = d[d["modality"] == "transfer_audio"].copy()
    vmain = v[(v["is_decoy"] != True) & (v["is_filler"] != True)      # noqa: E712
              & (v["check_kind"].isna()) & (v["target_char"].isin(CHARS))].copy()
    amain = a[(a["is_decoy"] != True) & (a["check_kind"].isna())      # noqa: E712
              & (a["target_char"].isin(CHARS))].copy()
    tail = amain["stimulus_id"].fillna("").astype(str).str.split("|").str[-1]
    amain["is_embedded_full"] = (tail == "full") & amain["gate_ms_f"].isna()
    print(f"  視覚 {len(vmain)}行 / {vmain['participant_id'].nunique()}人"
          f"（うち WebKit {vmain[vmain['webkit']]['participant_id'].nunique()}人）")
    print(f"  聴覚 はしご {int((~amain['is_embedded_full']).sum())}行 "
          f"/ {amain['participant_id'].nunique()}人")
    return vmain, amain


def gammas(d):
    gv = 1.0 / float(d[d["modality"] == "transfer_visual"]["n_choices"].mode().iloc[0])
    ga = 1.0 / float(d[d["modality"] == "transfer_audio"]["n_choices"].mode().iloc[0])
    print(f"  当て推量の下限 γ: 視覚=1/{round(1 / gv)}={gv:.5f} "
          f"聴覚=1/{round(1 / ga)}={ga:.5f}")
    return gv, ga


def visual_rows(vmain, fam):
    s = vmain[vmain["family"] == fam]
    if SPEED_BY_FAM[fam] is not None:
        s = s[s["base_anim_ms_i"] == SPEED_BY_FAM[fam]]
    if fam in WEBKIT_FAMILIES:
        s = s[~s["webkit"]]
    return s


class Cell:
    """1 セル（字×方式、または字×聴覚）の試行を、参加者×水準の行列にしたもの。

    K[p, j] = 参加者 p の水準 j での正答数、N[p, j] = 試行数。
    参加者単位のブートストラップが行の抽出だけで書ける。
    """

    def __init__(self, sub, level_key, gamma, name):
        self.name = name
        self.gamma = float(gamma)
        sub = sub[sub[level_key].notna()]
        self.xs = np.array(sorted(sub[level_key].unique()), dtype=float)
        pids = sorted(sub["participant_id"].astype(str).unique())
        self.pids = pids
        xi = {x: j for j, x in enumerate(self.xs)}
        pi = {p: i for i, p in enumerate(pids)}
        K = np.zeros((len(pids), len(self.xs)))
        N = np.zeros((len(pids), len(self.xs)))
        for p, x, c in zip(sub["participant_id"].astype(str).values,
                           sub[level_key].values, sub["correct_i"].values):
            i, j = pi[p], xi[float(x)]
            N[i, j] += 1.0
            K[i, j] += float(c)
        self.K, self.N = K, N
        self.k = K.sum(axis=0)
        self.n = N.sum(axis=0)
        self.n_trials = int(self.n.sum())

    @property
    def acc(self):
        return self.k / np.maximum(self.n, 1.0)

    def sub_rows(self, idx):
        """参加者の行を選んで (k, n) を作る（ブートストラップ・交差確認の共通道具）。"""
        return self.K[idx].sum(axis=0), self.N[idx].sum(axis=0)


# ===========================================================================
# 単調回帰（重み付き PAVA）
# ===========================================================================
def pava(y, w):
    """重み付き PAVA（隣接違反者プール法）。

    二項尤度のもとでの単調最尤解は、観測比率 y を重み n で重み付き最小二乗した
    単調回帰と一致する（Ayer et al. 1955）。ゆえにこれは「関数形を置かない最尤」である。
    """
    y = np.asarray(y, dtype=float)
    w = np.asarray(w, dtype=float)
    keep = w > 0
    if not keep.any():
        return np.zeros_like(y)
    yy, ww = y[keep], w[keep]
    # ブロック = [値, 重みの和, 元の点の数]。右から足しては違反を潰す。
    blocks = []
    for v, wt in zip(yy, ww):
        blocks.append([v, wt, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0] + 1e-15:
            v2, w2, l2 = blocks.pop()
            v1, w1, l1 = blocks.pop()
            tw = w1 + w2
            blocks.append([(v1 * w1 + v2 * w2) / tw, tw, l1 + l2])
    flat = np.concatenate([np.full(b[2], b[0]) for b in blocks])
    out = np.empty_like(y)
    out[keep] = flat
    # 重みゼロの水準（交差確認で試行が落ちたとき）は近い水準の値で埋める
    if (~keep).any():
        idx = np.where(keep)[0]
        for j in np.where(~keep)[0]:
            out[j] = out[idx[np.argmin(np.abs(idx - j))]]
        out = np.maximum.accumulate(out)
    return out


def n_blocks(vals):
    return int(1 + np.sum(np.diff(vals) > 1e-9))


# ===========================================================================
# 曲線の共通の型
# ===========================================================================
class Curve:
    """推定した単調曲線。p(x)（正答率）と逆関数を持つ。

    clamp=True … 測った範囲 [xlo, xhi] の外は端の値で一定（外挿しない）
    clamp=False … 母数形の式をそのまま外へ伸ばす（現行のロジスティック版の挙動）
    out_lo / out_hi … 逆引きが範囲外に出たときに返す x（視覚なら 0% / 100%）
    """

    kind = "?"

    def __init__(self, xs, gamma, clamp=True, out_lo=0.0, out_hi=100.0):
        self.xs = np.asarray(xs, dtype=float)
        self.xlo, self.xhi = float(self.xs.min()), float(self.xs.max())
        self.gamma = float(gamma)
        self.clamp = clamp
        self.out_lo, self.out_hi = out_lo, out_hi
        self.note = ""

    # --- 派生クラスが実装する ---
    def _raw(self, x):                                  # ndarray -> ndarray
        raise NotImplementedError

    def _raw_inv(self, y):                              # float -> float or None
        raise NotImplementedError

    # --- 共通 ---
    def pv(self, x):
        x = np.asarray(x, dtype=float)
        if self.clamp:
            x = np.clip(x, self.xlo, self.xhi)
        return np.clip(self._raw(x), 0.0, 1.0)

    def p(self, x):
        return float(self.pv(np.array([x]))[0])

    @property
    def lam(self):
        """天井。丸める版は測った上端の値、丸めない版は当てはめた λ。"""
        return float(self.pv(np.array([self.xhi]))[0])

    @property
    def floor(self):
        return float(self.pv(np.array([self.xlo]))[0])

    def q(self, x):
        d = self.lam - self.gamma
        if d <= EPS:
            return np.zeros_like(np.asarray(x, dtype=float))
        return np.clip((self.pv(x) - self.gamma) / d, 0.0, 1.0)

    def inv(self, y):
        """p(x) = y を x について解く（一般化逆＝ y に達する最小の x）。

        戻り値 (x, flag)。flag は "low"/"high"/None。
        """
        lo_p, hi_p = self.floor, self.lam
        if hi_p - lo_p <= EPS:
            return (self.out_lo, "low") if y <= hi_p else (self.out_hi, "high")
        if y <= lo_p:
            return self.out_lo, "low"
        if y >= hi_p:
            return self.out_hi, "high"
        x = self._raw_inv(y)
        if x is None or not np.isfinite(x):
            return self.out_lo, "low"
        x = min(max(x, self.xlo), self.xhi)
        return float(x), None

    def window(self, lo_meas, hi_meas):
        """組み合わせ用の窓 [s5, s95]（b3 と同じ定義）。

        q(s) が自分の可動域の 5% / 95% に達する s。曲線がロジスティックなら
        ちょうど μ∓2.944σ に一致する。実測水準の範囲に丸める（外挿しない）。
        """
        top = self.q(np.array([self.xhi]))[0]
        if top <= EPS:
            return lo_meas, hi_meas, lo_meas, hi_meas
        s5 = self._q_cross(0.05 * top)
        s95 = self._q_cross(0.95 * top)
        c5 = min(max(s5, lo_meas), hi_meas)
        c95 = min(max(s95, lo_meas), hi_meas)
        if c95 <= c5:
            c5, c95 = lo_meas, hi_meas
        return s5, s95, c5, c95

    def _q_cross(self, qt):
        y = self.gamma + qt * (self.lam - self.gamma)
        x, flag = self.inv(y)
        if flag == "low":
            return self.xlo
        if flag == "high":
            return self.xhi
        return x

    def deviance(self, k, n):
        p = np.clip(self.pv(self.xs), 1e-9, 1 - 1e-9)
        return float(-2.0 * np.sum(k * np.log(p) + (n - k) * np.log(1.0 - p)))


class PLCurve(Curve):
    """折れ線（水準を節点とする区分線形）。scale='log' なら区間ごとにべき乗。"""

    kind = "isotonic"

    def __init__(self, xs, ys, gamma, scale="log", **kw):
        super().__init__(xs, gamma, **kw)
        self.ys = np.maximum.accumulate(np.asarray(ys, dtype=float))
        self.scale = scale
        self.tx = np.log(np.maximum(self.xs, 1e-9)) if scale == "log" else self.xs.copy()

    def _t(self, x):
        return np.log(np.maximum(x, 1e-9)) if self.scale == "log" else x

    def _raw(self, x):
        return np.interp(self._t(x), self.tx, self.ys)

    def _raw_inv(self, y):
        j = int(np.searchsorted(self.ys, y, side="left"))
        j = min(max(j, 1), len(self.ys) - 1)
        y0, y1 = self.ys[j - 1], self.ys[j]
        if y1 - y0 <= EPS:
            t = self.tx[j - 1]
        else:
            t = self.tx[j - 1] + (y - y0) / (y1 - y0) * (self.tx[j] - self.tx[j - 1])
        return math.exp(t) if self.scale == "log" else t


class ConstCurve(Curve):
    kind = "const"

    def __init__(self, xs, c, gamma, **kw):
        super().__init__(xs, gamma, **kw)
        self.c = float(c)

    def _raw(self, x):
        return np.full_like(np.asarray(x, dtype=float), self.c)

    def _raw_inv(self, y):
        return self.xlo


class LinearCurve(Curve):
    kind = "linear"

    def __init__(self, xs, a, b, gamma, **kw):
        super().__init__(xs, gamma, **kw)
        self.a, self.b = float(a), max(0.0, float(b))

    def _raw(self, x):
        return np.clip(self.a + self.b * np.asarray(x, dtype=float), self.gamma, 1.0)

    def _raw_inv(self, y):
        if self.b <= EPS:
            return self.xlo
        return (y - self.a) / self.b


class StepCurve(Curve):
    kind = "step"

    def __init__(self, xs, theta, c0, c1, gamma, **kw):
        super().__init__(xs, gamma, **kw)
        self.theta, self.c0, self.c1 = float(theta), float(c0), float(max(c0, c1))

    def _raw(self, x):
        x = np.asarray(x, dtype=float)
        return np.where(x < self.theta, self.c0, self.c1)

    def _raw_inv(self, y):
        return self.theta if y > self.c0 + EPS else self.xlo


class ExpSatCurve(Curve):
    """指数飽和 p = c + (λ−c)(1 − exp(−x/τ))。床 c が自由（回答の偏りを吸収する）。"""

    kind = "expsat"

    def __init__(self, xs, c, lam, tau, gamma, **kw):
        super().__init__(xs, gamma, **kw)
        self.c, self.lam_p, self.tau = float(c), float(lam), max(float(tau), 1e-6)

    def _raw(self, x):
        x = np.maximum(np.asarray(x, dtype=float), 0.0)
        return self.c + (self.lam_p - self.c) * (1.0 - np.exp(-x / self.tau))

    def _raw_inv(self, y):
        d = self.lam_p - self.c
        if d <= EPS:
            return self.xlo
        r = 1.0 - (y - self.c) / d
        if r <= 1e-12:
            return self.xhi
        return -self.tau * math.log(r)


class LogisticCurve(Curve):
    kind = "logistic"

    def __init__(self, xs, lam, mu, sigma, gamma, **kw):
        super().__init__(xs, gamma, **kw)
        self.lam_p, self.mu = float(lam), float(mu)
        self.sigma = max(float(sigma), 1e-9)

    def _raw(self, x):
        z = np.clip(-(np.asarray(x, dtype=float) - self.mu) / self.sigma, -60.0, 60.0)
        return self.gamma + (self.lam_p - self.gamma) / (1.0 + np.exp(z))

    def _raw_inv(self, y):
        if self.lam_p <= self.gamma:
            return self.xlo
        num, den = y - self.gamma, self.lam_p - y
        if num <= 0 or den <= 0:
            return None
        return self.mu + self.sigma * math.log(num / den)

    # 現行版（clamp=False）は 0〜100 の外へ出たら丸める。b3 の invert() と同じ挙動。
    def inv(self, y):
        if self.clamp:
            return super().inv(y)
        if self.lam_p <= self.gamma or y <= self.gamma:
            return self.out_lo, "low"
        if y >= self.lam_p:
            return self.out_hi, "high"
        s = self.mu + self.sigma * math.log((y - self.gamma) / (self.lam_p - y))
        if s < self.out_lo:
            return self.out_lo, "low"
        if s > self.out_hi:
            return self.out_hi, "high"
        return float(s), None

    @property
    def lam(self):
        return self.lam_p if not self.clamp else super().lam

    @property
    def floor(self):
        return self.gamma if not self.clamp else super().floor


# ===========================================================================
# 候補の当てはめ
# ===========================================================================
def _nll(p, k, n):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.sum(k * np.log(p) + (n - k) * np.log(1 - p)))


def fit_const(xs, k, n, gamma, **kw):
    c = float(k.sum() / max(n.sum(), 1.0))
    return ConstCurve(xs, c, gamma, **kw)


def fit_linear(xs, k, n, gamma, **kw):
    m = n > 0
    if m.sum() < 2:
        return fit_const(xs, k, n, gamma, **kw)
    x, kk, nn = xs[m], k[m], n[m]
    acc = kk / nn

    def f(th):
        return _nll(np.clip(th[0] + th[1] * x, gamma, 1.0), kk, nn)

    rng = max(x.max() - x.min(), 1e-9)
    b0 = max((acc.max() - acc.min()) / rng, 1e-6)
    best, bestv = None, float("inf")
    for a0 in (gamma, acc.min(), acc[0]):
        for bm in (0.3, 1.0, 3.0):
            th0 = [a0, b0 * bm]
            if HAVE_SCIPY:
                r = minimize(f, th0, method="L-BFGS-B",
                             bounds=[(-1.0, 1.0), (0.0, 10.0 / rng)])
                th, v = r.x, r.fun
            else:
                th, v = th0, f(th0)
            if v < bestv:
                best, bestv = th, v
    return LinearCurve(xs, best[0], best[1], gamma, **kw)


def fit_step(xs, k, n, gamma, **kw):
    m = n > 0
    if m.sum() < 2:
        return fit_const(xs, k, n, gamma, **kw)
    x, kk, nn = xs[m], k[m], n[m]
    thetas = np.sqrt(x[:-1] * x[1:])            # 隣り合う水準の幾何平均だけを候補にする
    best, bestv = None, float("inf")
    for th in thetas:
        lo, hi = x < th, x >= th
        if nn[lo].sum() <= 0 or nn[hi].sum() <= 0:
            continue
        c0 = kk[lo].sum() / nn[lo].sum()
        c1 = kk[hi].sum() / nn[hi].sum()
        if c1 < c0:                              # 単調性を守る（潰れたら定数と同じ）
            c0 = c1 = kk.sum() / nn.sum()
        v = _nll(np.where(lo, c0, c1), kk, nn)
        if v < bestv:
            best, bestv = (th, c0, c1), v
    if best is None:
        return fit_const(xs, k, n, gamma, **kw)
    return StepCurve(xs, best[0], best[1], best[2], gamma, **kw)


def fit_expsat(xs, k, n, gamma, **kw):
    m = n > 0
    if m.sum() < 3:
        return fit_linear(xs, k, n, gamma, **kw)
    x, kk, nn = xs[m], k[m], n[m]
    acc = kk / nn

    def model(th):
        c = th[0]
        lam = c + (1.0 - c) * th[1]
        tau = max(th[2], 1e-6)
        return c + (lam - c) * (1.0 - np.exp(-np.maximum(x, 0.0) / tau))

    def f(th):
        return _nll(model(th), kk, nn)

    c0 = float(np.clip(acc.min(), 0.0, 0.9))
    best, bestv = None, float("inf")
    span = max(x.max(), 1e-6)
    for tau0 in (span / 20, span / 6, span / 2, span * 1.5):
        th0 = [c0, 0.9, tau0]
        if HAVE_SCIPY:
            r = minimize(f, th0, method="L-BFGS-B",
                         bounds=[(0.0, 0.95), (0.0, 1.0), (span * 1e-4, span * 50)])
            th, v = r.x, r.fun
        else:
            th, v = th0, f(th0)
        if v < bestv:
            best, bestv = th, v
    c = best[0]
    lam = c + (1.0 - c) * best[1]
    return ExpSatCurve(xs, c, lam, best[2], gamma, **kw)


def fit_logistic(xs, k, n, gamma, n_starts=8, **kw):
    f = acf.fit_sigmoid(xs, k, n, gamma, n_starts=n_starts)
    if not np.isfinite(f["mu"]) or not np.isfinite(f["sigma"]):
        return fit_const(xs, k, n, gamma, **kw)
    c = LogisticCurve(xs, f["lam"], f["mu"], f["sigma"], gamma, **kw)
    c.note = f.get("note", "")
    c.fit_raw = f
    return c


def fit_isotonic(cell, idx=None, bag=200, seed=0, scale="log", **kw):
    """袋詰め PAVA。idx は使う参加者の行（交差確認のとき部分集合になる）。

    平滑化の強さは人が決めない。参加者の入れ替わりで PAVA の段の位置が動く量、
    すなわち**データ自身のばらつき**がならしの量を決める。
    """
    if idx is None:
        idx = np.arange(len(cell.pids))
    k, n = cell.sub_rows(idx)
    base = pava(k / np.maximum(n, 1.0), n)
    if bag <= 0:
        return PLCurve(cell.xs, base, cell.gamma, scale=scale, **kw), base
    rng = np.random.default_rng(seed)
    acc = np.zeros(len(cell.xs))
    P = len(idx)
    for _ in range(bag):
        draw = idx[rng.integers(0, P, size=P)]
        kb, nb = cell.sub_rows(draw)
        acc += pava(kb / np.maximum(nb, 1.0), nb)
    ys = acc / bag
    return PLCurve(cell.xs, ys, cell.gamma, scale=scale, **kw), base


FITTERS = {
    "const": lambda c, idx, o: fit_const(c.xs, *c.sub_rows(idx), c.gamma, **o),
    "linear": lambda c, idx, o: fit_linear(c.xs, *c.sub_rows(idx), c.gamma, **o),
    "step": lambda c, idx, o: fit_step(c.xs, *c.sub_rows(idx), c.gamma, **o),
    "expsat": lambda c, idx, o: fit_expsat(c.xs, *c.sub_rows(idx), c.gamma, **o),
    "logistic": lambda c, idx, o: fit_logistic(c.xs, *c.sub_rows(idx), c.gamma, **o),
}


def fit_candidate(kind, cell, idx, opts, bag, seed, scale):
    if kind == "isotonic":
        return fit_isotonic(cell, idx, bag=bag, seed=seed, scale=scale, **opts)[0]
    return FITTERS[kind](cell, idx, opts)


# ===========================================================================
# 形を選ぶ（参加者単位の 5 分割交差確認 + 1SE 則）
# ===========================================================================
def cv_select(cell, opts, folds=5, seed=20260828, bag=200, scale="log",
              cands=CAND_ORDER):
    P = len(cell.pids)
    # 乱数の種はセル名から決める（ハッシュの乱数化に左右されないよう crc32 を使う）
    rng = np.random.default_rng(seed + zlib.crc32(cell.name.encode("utf-8")) % 100000)
    order = rng.permutation(P)
    assign = np.zeros(P, dtype=int)
    for i, p in enumerate(order):
        assign[p] = i % folds
    dev = {c: [] for c in cands}
    for f in range(folds):
        tr = np.where(assign != f)[0]
        te = np.where(assign == f)[0]
        if len(tr) == 0 or len(te) == 0:
            continue
        kte, nte = cell.sub_rows(te)
        for c in cands:
            try:
                cv = fit_candidate(c, cell, tr, opts, bag=max(bag // 4, 25),
                                   seed=seed + f, scale=scale)
                p = np.clip(cv.pv(cell.xs), 1e-9, 1 - 1e-9)
                d = -2.0 * np.sum(kte * np.log(p) + (nte - kte) * np.log(1 - p))
            except Exception:
                d = float("inf")
            dev[c].append(float(d))
    rows = []
    means, ses = {}, {}
    for c in cands:
        a = np.array(dev[c], dtype=float)
        a = a[np.isfinite(a)]
        means[c] = float(a.mean()) if len(a) else float("inf")
        ses[c] = float(a.std(ddof=1) / math.sqrt(len(a))) if len(a) > 1 else float("nan")
        rows.append(dict(cell=cell.name, candidate=c, candidate_ja=CAND_JA[c],
                         n_par=CAND_NPAR[c], cv_deviance_mean=means[c],
                         cv_deviance_se=ses[c], n_folds=int(len(a))))
    best = min(cands, key=lambda c: means[c])
    thr = means[best] + (ses[best] if np.isfinite(ses[best]) else 0.0)
    chosen = next((c for c in cands if means[c] <= thr + 1e-12), best)
    for r in rows:
        r["is_best"] = (r["candidate"] == best)
        r["chosen_1se"] = (r["candidate"] == chosen)
        r["threshold_1se"] = thr
    return chosen, rows, means


# ===========================================================================
# 表を作る（b3 の build() を Curve 型に載せ替えたもの。写し方・対照は同じ）
# ===========================================================================
def qmap_window(c5, c95):
    """u（0〜1）→ その方式の進み具合 s（%）。b3 の linear と同じ。"""
    out = [c5 + (c95 - c5) * (i / (N_MAP - 1)) for i in range(N_MAP)]
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1])
    return out


def fit_b2(ts, targ, cv):
    """対照2: 開始と速さだけ最適に合わせた直線（b3 と同じ総当たり。numpy で速く）。"""
    a = (np.arange(1, 601) * (100.0 / BASE_ANIM_MS) / 100.0 * 2.0)[:, None, None]
    b = (np.arange(-40, 41) * 0.5)[None, :, None]
    t = np.asarray(ts)[None, None, :]
    s = np.clip(a * t + b, 0.0, 100.0)
    pred = cv.pv(s.ravel()).reshape(s.shape)
    e = ((pred - np.asarray(targ)[None, None, :]) ** 2).sum(axis=2)
    i, j = np.unravel_index(np.argmin(e), e.shape)
    return float(a[i, 0, 0]), float(b[0, j, 0])


def build(FV, FA, levels, tag):
    n = int(math.ceil(DURATION_MS / FRAME_MS)) + 1
    ts = [i * FRAME_MS for i in range(n)]
    tables, ranges, log, winrows = {}, {}, [], []

    for fam in FAMS:
        tables[fam] = {}
        for ch in CHARS:
            ca, cv = FA[ch], FV[(ch, fam)]
            targ = list(ca.pv(np.array(ts)))
            prop, nlo, nhi = [], 0, 0
            for y in targ:
                s, cl = cv.inv(y)
                nlo += (cl == "low")
                nhi += (cl == "high")
                prop.append(s)
            for i in range(1, len(prop)):
                prop[i] = max(prop[i], prop[i - 1])
            b1 = [max(0.0, min(100.0, 100.0 * t / BASE_ANIM_MS)) for t in ts]
            a, b = fit_b2(ts, targ, cv)
            b2 = [max(0.0, min(100.0, a * t + b)) for t in ts]
            tables[fam][ch] = {"proposed": [round(x / 100.0, 8) for x in prop],
                               "baseline1": [round(x / 100.0, 8) for x in b1],
                               "baseline2": [round(x / 100.0, 8) for x in b2]}
            jumps = np.diff(prop)
            log.append(dict(estimator=tag, family=fam, char=ch, clip_low=int(nlo),
                            clip_high=int(nhi), s_min=round(min(prop), 4),
                            s_max=round(max(prop), 4),
                            span_pt=round(max(prop) - min(prop), 4),
                            max_jump_pt=round(float(jumps.max()) if len(jumps) else 0.0, 4),
                            n_jump_over_25pt=int((jumps > 25).sum()),
                            b2_a=round(a, 5), b2_b=round(b, 3)))

    for fa, fb in PAIRS:
        key = fa + "+" + fb
        tables[key] = {}
        ranges[key] = {}
        for ch in CHARS:
            ca = FA[ch]
            cva, cvb = FV[(ch, fa)], FV[(ch, fb)]
            wa = cva.window(*levels[fa])
            wb = cvb.window(*levels[fb])
            ma, mb = qmap_window(wa[2], wa[3]), qmap_window(wb[2], wb[3])
            for fam_, w_, cc in ((fa, wa, cva), (fb, wb, cvb)):
                winrows.append(dict(estimator=tag, pair=key, family=fam_, char=ch,
                                    curve=cc.kind, s5_raw=w_[0], s95_raw=w_[1],
                                    level_min_tested=levels[fam_][0],
                                    level_max_tested=levels[fam_][1],
                                    s5_clipped=w_[2], s95_clipped=w_[3],
                                    clipped_low=bool(w_[0] < levels[fam_][0]),
                                    clipped_high=bool(w_[1] > levels[fam_][1])))
            lam = min(cva.lam, cvb.lam)
            g = cva.gamma

            def at(m, u):
                x = max(0.0, min(1.0, u / 100.0)) * (N_MAP - 1)
                i = int(x)
                j = min(i + 1, N_MAP - 1)
                f = x - i
                return m[i] * (1 - f) + m[j] * f

            def P(u):
                return g + (lam - g) * float(cva.q(np.array([at(ma, u)]))[0]) \
                             * float(cvb.q(np.array([at(mb, u)]))[0])

            targ = list(ca.pv(np.array(ts)))
            bot, top = P(0.0), P(100.0)
            prop, nlo, nhi = [], 0, 0
            for y in targ:
                if y <= bot:
                    prop.append(0.0)
                    nlo += 1
                    continue
                if y >= top:
                    prop.append(100.0)
                    nhi += 1
                    continue
                lo_, hi_ = 0.0, 100.0
                for _ in range(50):
                    mid = (lo_ + hi_) / 2
                    if P(mid) < y:
                        lo_ = mid
                    else:
                        hi_ = mid
                prop.append((lo_ + hi_) / 2)
            for i in range(1, len(prop)):
                prop[i] = max(prop[i], prop[i - 1])
            b1 = [max(0.0, min(100.0, 100.0 * t / BASE_ANIM_MS)) for t in ts]
            s0, s1 = prop[0], prop[-1]
            b2 = [max(0.0, min(100.0, s0 + (s1 - s0) * i / max(1, len(ts) - 1)))
                  for i in range(len(ts))]
            tables[key][ch] = {"proposed": [round(x / 100.0, 8) for x in prop],
                               "baseline1": [round(x / 100.0, 8) for x in b1],
                               "baseline2": [round(x / 100.0, 8) for x in b2]}
            ranges[key][ch] = {"a": [round(x, 4) for x in ma],
                               "b": [round(x, 4) for x in mb]}
            jumps = np.diff(prop)
            log.append(dict(estimator=tag, family=key, char=ch, clip_low=int(nlo),
                            clip_high=int(nhi), s_min=round(min(prop), 4),
                            s_max=round(max(prop), 4),
                            span_pt=round(max(prop) - min(prop), 4),
                            max_jump_pt=round(float(jumps.max()) if len(jumps) else 0.0, 4),
                            n_jump_over_25pt=int((jumps > 25).sum()),
                            b2_a=0, b2_b=0))
    return tables, ranges, log, winrows


def write_json(path, tables, ranges, tag, note):
    doc = {"generated_by": "experiment/tools/build_warp_b4.py",
           "estimator": tag,
           "frame_ms": round(FRAME_MS, 6),
           "duration_ms": DURATION_MS,
           "base_anim_ms": BASE_ANIM_MS,
           "meta": {"space": "rawp", "made": "2026-08-28", "chars": CHARS,
                    "visual_source": "calib+calib2 両バッチ / 速さ: " + ", ".join(
                        f"{f}={'300ms' if SPEED_BY_FAM[f] else '2水準'}" for f in FAMS),
                    "webkit_excluded_families": sorted(WEBKIT_FAMILIES),
                    "audio_source": "実験1(phase=calib)・速さの区別なし",
                    "composite_mapping": "linear（字ごとの窓・build_warp_b3.py と同じ）",
                    "curve_estimator": tag, "note": note},
           "composite_map": ranges, "composite_map_n": N_MAP,
           "tables": tables}
    json.dump(doc, io.open(path, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"  書き出し: {os.path.basename(path)} ({os.path.getsize(path)//1024} KB)")
    return doc


# ===========================================================================
# 描き分けられる絵の枚数（分解能）
# ===========================================================================
# analyze_families_v2.py の b_resolution_limit() と同じ数え方を、
# **warp が実際になぞる道の上**で数え直す。
#   うすい     … 不透明度 round(255·s^gamma)                 全256階調
#   点が増える … 見せる墨画素の数 round(ink·s)
#   ぼやけ     … ぼかし半径 72·(1−s) px（transfer.js は toFixed(2) で 0.01px 刻み）
#   端から     … 見せる列の数 round(bbox幅·s)
#
# ⚠ 組み合わせの分解能は **掛け算にならない**。
#   アニメは u を 0→1 と一方向に進む1本の道なので、格子(6×27=162)の全点は通らない。
#   道の上で絵が変わるのは「どちらかの方式が段を1つまたいだ瞬間」だけなので、
#   枚数は**足し算**（およそ n_a + n_b − 1）になる。
#   それでも単体の頭打ちは越えられる（うすい6枚が 6+27−1=32枚 になる）。
BLUR_MAX_PX = 72.0
FADE_GAMMA = 1.0


def glyph_stats(base_dir):
    """字ごとの墨画素数と bbox 幅（点が増える・端から の段数に要る）。"""
    try:
        from PIL import Image
    except Exception:
        print("  ⚠ PIL が無いので分解能の数えは点が増える・端からを飛ばす")
        return {}, {}
    ink, bw = {}, {}
    for ch in CHARS:
        p = os.path.join(base_dir, ch + ".png")
        if not os.path.exists(p):
            continue
        arr = np.asarray(Image.open(p).convert("L"), dtype=float)
        m = arr < 128
        ink[ch] = int(m.sum())
        xs = np.nonzero(m.any(axis=0))[0]
        bw[ch] = int(xs.max() - xs.min() + 1) if len(xs) else 0
    return ink, bw


def quant_levels(fam, ch, s_pct, ink, bw, blur_px_step=1.0):
    """進み具合 s(%) の並びを、その方式が実際に出す『絵の識別子』に量子化する。

    blur_px_step … ぼかし半径を何 px 刻みで別の絵と数えるか。
      既定 1.0 は analyze_families_v2.py の resolution_limit.csv と同じ数え方
      （半径 72px を 1px 刻み＝全72段）。transfer.js は toFixed(2) で
      0.01px まで指定できるが、0.01px の違いが別の絵になるとは言えないので、
      比較のときは 1px を使う（0.01px 版は上限の目安として別欄に出す）。
    """
    s = np.clip(np.asarray(s_pct, dtype=float) / 100.0, 0.0, 1.0)
    if fam == "fade":
        return np.round(255.0 * s ** FADE_GAMMA)
    if fam == "reveal":
        return np.round(ink.get(ch, 0) * s)
    if fam == "blur":
        return np.round(BLUR_MAX_PX * (1.0 - s) / blur_px_step)
    if fam == "wipe":
        return np.round(bw.get(ch, 0) * s)
    raise KeyError(fam)


def n_distinct(*level_arrays):
    """複数方式を重ねたときの、道の上で見える別々の絵の枚数。"""
    stack = np.vstack(level_arrays)
    changes = np.any(np.diff(stack, axis=1) != 0, axis=0)
    return int(1 + changes.sum())


# ===========================================================================
# 比較
# ===========================================================================
def _series_at(arr, ms):
    """transfer.js の seriesAt と同じ線形補間で数値列を読む。"""
    n = len(arr)
    x = np.clip(np.asarray(ms, dtype=float) / FRAME_MS, 0, n - 1)
    lo = np.floor(x).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    f = x - lo
    return arr[lo] * (1 - f) + arr[hi] * f


def _ref_acc(fam, ch, s_pct, ref_FV, cmap):
    """共通の参照曲線（袋詰め PAVA）で「その絵が読める確率」を返す。

    どの推定でも同じ物差しで測れるようにするための、比較専用の関数である。
    """
    if fam in FAMS:
        return ref_FV[(ch, fam)].pv(s_pct)
    fa, fb = fam.split("+")
    ca, cb = ref_FV[(ch, fa)], ref_FV[(ch, fb)]
    m = cmap[fam][ch]
    u = np.clip(np.asarray(s_pct, dtype=float) / 100.0, 0.0, 1.0) * (N_MAP - 1)
    lo = np.floor(u).astype(int)
    hi = np.minimum(lo + 1, N_MAP - 1)
    f = u - lo
    sa = np.array(m["a"])[lo] * (1 - f) + np.array(m["a"])[hi] * f
    sb = np.array(m["b"])[lo] * (1 - f) + np.array(m["b"])[hi] * f
    lam = min(ca.lam, cb.lam)
    g = ca.gamma
    return g + (lam - g) * ca.q(sa) * cb.q(sb)


def compare(built, FVs, FAs, ref_FV, ref_FA, ink=None, bw=None):
    """セルごとの比較。物差しは3つ。

    ① 進み具合の空間（pt）… 提案と対照2が「どれだけ違う絵を出すか」
    ② 正答率の空間（pt）… 参加者が実際に受け取る「読める確率」の差。
       方式ごとに進み具合の目盛りの意味が違うので、条件の違いを比べるならこちら。
    ③ 目標軌跡の再現 … 逆引きした s を**共通の参照曲線**に通し、聴覚の目標との差を測る。
       提案条件が主張どおりのことをしているかは、これで決まる。
    加えて **一次変換への潰れ具合**（提案の軌跡を時間の直線で近似したときの残差）と
    **分解能**（道の上で実際に何枚の別々の絵が出るか）を測る。
    ⚠ 打ち切り時点より後は参加者に見えないので、②③と一次変換の判定は
      **その字の最大打ち切り時刻までの窓**で測る。
    """
    ink = ink or {}
    bw = bw or {}
    rows = []
    for tag, doc in built.items():
        FV, FA = FVs[tag], FAs[tag]
        cmap = doc.get("composite_map", {})
        for fam in list(FAMS) + [x + "+" + y for x, y in PAIRS]:
            for ch in CHARS:
                T = doc["tables"][fam][ch]
                pr_a = np.array(T["proposed"]) * 100
                b1_a = np.array(T["baseline1"]) * 100
                b2_a = np.array(T["baseline2"]) * 100
                gs = np.array(GATES_MS.get(ch, GATES_MS["_default"]), dtype=float)
                tw = np.linspace(0.0, float(gs.max()), 601)    # 参加者が見る窓
                pr, b1, b2 = (_series_at(x, tw) for x in (pr_a, b1_a, b2_a))
                prg, b1g, b2g = (_series_at(x, gs) for x in (pr_a, b1_a, b2_a))

                # ② 正答率の空間（共通の参照曲線）
                ap, a1, a2 = (_ref_acc(fam, ch, x, ref_FV, cmap) * 100
                              for x in (prg, b1g, b2g))
                tgt = ref_FA[ch].pv(gs) * 100
                # ③ 自分の推定で見た再現（逆引きが効いているかの内部確認）
                if fam in FAMS:
                    self_tg = FA[ch].pv(gs)
                    self_rmse = float(np.sqrt(np.mean(
                        (FV[(ch, fam)].pv(prg) - self_tg) ** 2))) * 100
                else:
                    self_rmse = float("nan")

                # 一次変換への潰れ具合（端に張り付いた区間を除く）
                A = np.vstack([tw, np.ones_like(tw)]).T
                co, *_ = np.linalg.lstsq(A, pr, rcond=None)
                res = pr - A @ co
                free = (pr > 0.02) & (pr < 99.98)
                span_w = float(pr.max() - pr.min())
                aff = float(np.sqrt(np.mean(res[free] ** 2))) if free.sum() > 3 \
                    else float(np.sqrt(np.mean(res ** 2)))

                # 分解能：道の上で実際に出る別々の絵の枚数
                nd = ndg = float("nan")
                if fam in FAMS:
                    try:
                        nd = n_distinct(quant_levels(fam, ch, pr, ink, bw))
                        ndg = len(np.unique(quant_levels(fam, ch, prg, ink, bw)))
                    except Exception:
                        pass
                elif fam in cmap:
                    fa_, fb_ = fam.split("+")
                    m = cmap[fam][ch]
                    u = np.clip(pr / 100.0, 0, 1) * (N_MAP - 1)
                    lo = np.floor(u).astype(int)
                    hi = np.minimum(lo + 1, N_MAP - 1)
                    f = u - lo
                    sa = np.array(m["a"])[lo] * (1 - f) + np.array(m["a"])[hi] * f
                    sb = np.array(m["b"])[lo] * (1 - f) + np.array(m["b"])[hi] * f
                    ug = np.clip(prg / 100.0, 0, 1) * (N_MAP - 1)
                    lg_ = np.floor(ug).astype(int)
                    hg_ = np.minimum(lg_ + 1, N_MAP - 1)
                    fg_ = ug - lg_
                    sag = np.array(m["a"])[lg_] * (1 - fg_) + np.array(m["a"])[hg_] * fg_
                    sbg = np.array(m["b"])[lg_] * (1 - fg_) + np.array(m["b"])[hg_] * fg_
                    try:
                        nd = n_distinct(quant_levels(fa_, ch, sa, ink, bw),
                                        quant_levels(fb_, ch, sb, ink, bw))
                        ndg = np.unique(np.stack([
                            quant_levels(fa_, ch, sag, ink, bw),
                            quant_levels(fb_, ch, sbg, ink, bw)]), axis=1).shape[1]
                    except Exception:
                        pass

                jumps = np.diff(pr_a)
                rows.append(dict(
                    estimator=tag, family=fam, char=ch,
                    curve_kind=(FV[(ch, fam)].kind if fam in FAMS else ""),
                    audio_kind=FA[ch].kind,
                    # ① 進み具合の空間
                    d_b2_frames=float(np.abs(pr_a - b2_a).mean()),
                    d_b1_frames=float(np.abs(pr_a - b1_a).mean()),
                    d_b2_gates=float(np.abs(prg - b2g).mean()),
                    d_b1_gates=float(np.abs(prg - b1g).mean()),
                    span_pt=float(pr_a.max() - pr_a.min()), span_pt_window=span_w,
                    # ② 正答率の空間
                    acc_d_b2=float(np.abs(ap - a2).mean()),
                    acc_d_b1=float(np.abs(ap - a1).mean()),
                    acc_span=float(ap.max() - ap.min()),
                    # ③ 目標の再現
                    rmse_target_proposed=float(np.sqrt(np.mean((ap - tgt) ** 2))),
                    rmse_target_b2=float(np.sqrt(np.mean((a2 - tgt) ** 2))),
                    rmse_target_b1=float(np.sqrt(np.mean((a1 - tgt) ** 2))),
                    rmse_self_proposed=self_rmse,
                    # ★ 仮説そのものの量：提案は対照2より、どれだけ目標に近いか
                    gain_over_b2=float(np.sqrt(np.mean((a2 - tgt) ** 2))
                                       - np.sqrt(np.mean((ap - tgt) ** 2))),
                    # 一次変換への潰れ具合・なめらかさ・分解能
                    affine_resid_pt=aff,
                    affine_resid_rel=aff / max(span_w, 1e-9),
                    n_distinct_images=nd, n_distinct_at_gates=ndg,
                    max_jump_pt=float(jumps.max()) if len(jumps) else 0.0,
                    n_jump_over_25pt=int((jumps > 25).sum())))
    return pd.DataFrame(rows)


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp",
                    default=os.path.join(ROOT,
                                         "project/data_calib2_live/transfer_trials.csv"))
    ap.add_argument("--out",
                    default=os.path.join(ROOT, "project/data_calib2_live/warp_v4"))
    ap.add_argument("--bag", type=int, default=200, help="袋詰め PAVA の袋の数")
    ap.add_argument("--cv-folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260828)
    ap.add_argument("--fit-starts", type=int, default=8)
    ap.add_argument("--interp", choices=["log", "linear"], default="log",
                    help="水準と水準のあいだの補間の目盛り")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    print("速さの絞り方: " + " ".join(
        f"{f}={'300ms' if SPEED_BY_FAM[f] else '2水準'}" for f in FAMS))
    print(f"ぼやけの WebKit 除外: {sorted(WEBKIT_FAMILIES)}")

    d = load_trials(a.inp)
    vmain, amain = slices(d)
    gv, ga = gammas(d)

    # ---- セルを作る ----
    ladder = amain[~amain["is_embedded_full"]]
    full = amain[amain["is_embedded_full"]]
    Acell = {ch: Cell(ladder[ladder["target_char"] == ch], "gate_ms_f", ga, f"audio|{ch}")
             for ch in CHARS}
    Vcell = {}
    levels = {}
    for fam in FAMS:
        base = visual_rows(vmain, fam)
        s = base["actual_s_pct"].dropna()
        levels[fam] = (float(s.min()), float(s.max()))
        for ch in CHARS:
            Vcell[(ch, fam)] = Cell(base[base["target_char"] == ch], "actual_s_pct",
                                    gv, f"{fam}|{ch}")
    print("\n実測した水準の範囲（この外へは外挿しない）")
    for fam in FAMS:
        print(f"  {fam:<7}{levels[fam][0]:>8.2f}% 〜 {levels[fam][1]:>7.2f}%  "
              f"水準{len(Vcell[(CHARS[0], fam)].xs)}点")
    print("  audio  " + " / ".join(
        f"{ch}:{Acell[ch].xs.min():.0f}〜{Acell[ch].xs.max():.0f}ms" for ch in CHARS))

    # =====================================================================
    # 1) ロジスティック版（現行の推定。b3 と同じ λ の下支えも入れる）
    # =====================================================================
    print("\n[1/3] ロジスティック当てはめ（現行版の再現）")
    FV_log, FA_log, FV_logc, FA_logc = {}, {}, {}, {}
    fitrows = []
    for ch in CHARS:
        c = Acell[ch]
        obs = float(full[full["target_char"] == ch]["correct_i"].mean()) \
            if len(full[full["target_char"] == ch]) else float("nan")
        f = fit_logistic(c.xs, c.k, c.n, ga, n_starts=a.fit_starts,
                         clamp=False, out_lo=0.0, out_hi=float(c.xs.max()))
        # b3 と同じ: 当てはめ λ が実測の全部聞かせた正答率を下回るときは実測を使う
        if np.isfinite(obs):
            f.lam_p = max(f.lam_p, obs)
        FA_log[ch] = f
        fc = fit_logistic(c.xs, c.k, c.n, ga, n_starts=a.fit_starts, clamp=True,
                          out_lo=float(c.xs.min()), out_hi=float(c.xs.max()))
        FA_logc[ch] = fc
        fitrows.append(dict(estimator="logistic", modality="audio", char=ch, family="",
                            kind="logistic", lam=f.lam_p, mu=f.mu, sigma=f.sigma,
                            floor=f.floor, n_trials=c.n_trials,
                            n_levels=len(c.xs), lambda_observed_full=obs,
                            deviance=f.deviance(c.k, c.n), note=f.note))
    for fam in FAMS:
        for ch in CHARS:
            c = Vcell[(ch, fam)]
            fullv = visual_rows(vmain, fam)
            fullv = fullv[(fullv["target_char"] == ch) & (fullv["progress_pct"] == 100)]
            obs = float(fullv["correct_i"].mean()) if len(fullv) else float("nan")
            f = fit_logistic(c.xs, c.k, c.n, gv, n_starts=a.fit_starts,
                             clamp=False, out_lo=0.0, out_hi=100.0)
            if np.isfinite(obs):
                f.lam_p = max(f.lam_p, obs)
            FV_log[(ch, fam)] = f
            FV_logc[(ch, fam)] = fit_logistic(c.xs, c.k, c.n, gv, n_starts=a.fit_starts,
                                              clamp=True, out_lo=0.0, out_hi=100.0)
            fitrows.append(dict(estimator="logistic", modality="visual", char=ch,
                                family=fam, kind="logistic", lam=f.lam_p, mu=f.mu,
                                sigma=f.sigma, floor=f.floor, n_trials=c.n_trials,
                                n_levels=len(c.xs), lambda_observed_full=obs,
                                deviance=f.deviance(c.k, c.n), note=f.note))

    # =====================================================================
    # 2) 単調回帰版（袋詰め PAVA）
    # =====================================================================
    print(f"[2/3] 単調回帰（袋詰め PAVA・袋 {a.bag}・参加者単位・補間 {a.interp}）")
    FV_iso, FA_iso = {}, {}
    smooth_rows = []
    for ch in CHARS:
        c = Acell[ch]
        cur, base = fit_isotonic(c, bag=a.bag, seed=a.seed, scale=a.interp,
                                 clamp=True, out_lo=float(c.xs.min()),
                                 out_hi=float(c.xs.max()))
        FA_iso[ch] = cur
        fitrows.append(dict(estimator="isotonic", modality="audio", char=ch, family="",
                            kind="isotonic", lam=cur.lam, mu=float("nan"),
                            sigma=float("nan"), floor=cur.floor, n_trials=c.n_trials,
                            n_levels=len(c.xs), lambda_observed_full=float("nan"),
                            deviance=cur.deviance(c.k, c.n),
                            note=f"PAVAの段={n_blocks(base)}"))
        for B in (0, 50, 100, 200, 400):
            cb, _ = fit_isotonic(c, bag=B, seed=a.seed, scale=a.interp, clamp=True,
                                 out_lo=float(c.xs.min()), out_hi=float(c.xs.max()))
            smooth_rows.append(dict(cell=c.name, bag=B,
                                    max_abs_diff_vs_pava=float(np.max(np.abs(cb.ys - base))),
                                    n_flat_steps=int(np.sum(np.diff(cb.ys) < 1e-6)),
                                    ys="|".join(f"{y:.4f}" for y in cb.ys)))
    for fam in FAMS:
        for ch in CHARS:
            c = Vcell[(ch, fam)]
            cur, base = fit_isotonic(c, bag=a.bag, seed=a.seed, scale=a.interp,
                                     clamp=True, out_lo=0.0, out_hi=100.0)
            FV_iso[(ch, fam)] = cur
            fitrows.append(dict(estimator="isotonic", modality="visual", char=ch,
                                family=fam, kind="isotonic", lam=cur.lam,
                                mu=float("nan"), sigma=float("nan"), floor=cur.floor,
                                n_trials=c.n_trials, n_levels=len(c.xs),
                                lambda_observed_full=float("nan"),
                                deviance=cur.deviance(c.k, c.n),
                                note=f"PAVAの段={n_blocks(base)}"))
            for B in (0, 50, 100, 200, 400):
                cb, _ = fit_isotonic(c, bag=B, seed=a.seed, scale=a.interp, clamp=True,
                                     out_lo=0.0, out_hi=100.0)
                smooth_rows.append(dict(cell=c.name, bag=B,
                                        max_abs_diff_vs_pava=float(np.max(np.abs(cb.ys - base))),
                                        n_flat_steps=int(np.sum(np.diff(cb.ys) < 1e-6)),
                                        ys="|".join(f"{y:.4f}" for y in cb.ys)))
    pd.DataFrame(smooth_rows).to_csv(os.path.join(a.out, "smoothing_sensitivity.csv"),
                                     index=False)

    # =====================================================================
    # 3) 字ごとに形を選ぶ版
    # =====================================================================
    print(f"[3/3] 字ごとに形を選ぶ（{a.cv_folds}分割・参加者単位）")
    # 選び方の規則を **2 つとも** 出す。どちらも手続きは同じで、決め方だけが違う。
    #   bestcv … 交差確認の逸脱度が最小の候補。「新しい参加者を一番よく当てる形」
    #   1se  … 最小から1標準誤差以内でいちばん単純な候補。過適合により慎重
    # ⚠ どちらを採るかは丸山さんの判断。ここは両方を同じ手続きで作って並べるだけ。
    FVsel = {"bestcv": {}, "1se": {}}
    FAsel = {"bestcv": {}, "1se": {}}
    selrows, seltab = [], []
    cells_all = [("audio", "", ch, Acell[ch]) for ch in CHARS] + \
                [("visual", fam, ch, Vcell[(ch, fam)]) for fam in FAMS for ch in CHARS]
    for mod, fam, ch, c in cells_all:
        opts = dict(clamp=True, out_lo=(float(c.xs.min()) if mod == "audio" else 0.0),
                    out_hi=(float(c.xs.max()) if mod == "audio" else 100.0))
        kind1, rows, means = cv_select(c, opts, folds=a.cv_folds, seed=a.seed,
                                       bag=a.bag, scale=a.interp)
        kindb = min(CAND_ORDER, key=lambda k: means[k])
        selrows += rows
        chosen = {"1se": kind1, "bestcv": kindb}
        for rule, kd in chosen.items():
            cur = fit_candidate(kd, c, np.arange(len(c.pids)), opts, a.bag, a.seed,
                                a.interp)
            if mod == "audio":
                FAsel[rule][ch] = cur
            else:
                FVsel[rule][(ch, fam)] = cur
            fitrows.append(dict(estimator="selected_" + rule, modality=mod, char=ch,
                                family=fam, kind=kd, lam=cur.lam,
                                mu=getattr(cur, "mu", float("nan")),
                                sigma=getattr(cur, "sigma", float("nan")),
                                floor=cur.floor, n_trials=c.n_trials,
                                n_levels=len(c.xs), lambda_observed_full=float("nan"),
                                deviance=cur.deviance(c.k, c.n), note=CAND_JA[kd]))
        seltab.append(dict(modality=mod, char=ch, family=fam,
                           chosen_bestcv=kindb, chosen_bestcv_ja=CAND_JA[kindb],
                           chosen_1se=kind1, chosen_1se_ja=CAND_JA[kind1],
                           # この升に「形を語れるだけの情報があるか」の目安。
                           # 定数より何点よくなるかで測る。0 に近いなら形は決められない。
                           signal_vs_const=round(means["const"] - means[kindb], 1),
                           n_trials=c.n_trials, n_levels=len(c.xs),
                           **{f"cv_{k}": round(v, 1) for k, v in means.items()}))
    pd.DataFrame(selrows).to_csv(os.path.join(a.out, "model_selection.csv"), index=False)
    seldf = pd.DataFrame(seltab)
    seldf.to_csv(os.path.join(a.out, "model_selection_table.csv"), index=False)
    pd.DataFrame(fitrows).to_csv(os.path.join(a.out, "fit_curves.csv"), index=False)

    for rule, col in (("最良CV", "chosen_bestcv_ja"), ("1SE則", "chosen_1se_ja")):
        print(f"\n■ どの字にどの形が選ばれたか（{rule}）")
        print(f"  {'':<10}" + "".join(f"{ch:<8}" for ch in CHARS))
        for mod, fam in [("audio", "")] + [("visual", f) for f in FAMS]:
            lab = "聴覚" if mod == "audio" else LAB[fam]
            mark = "  ←主軸" if fam in FAMS_MAIN else ""
            r = {x["char"]: x[col] for x in seltab
                 if x["modality"] == mod and x["family"] == fam}
            print(f"  {lab:<12}" + "".join(f"{r[ch]:<8}" for ch in CHARS) + mark)
    print("\n■ その升に形を語れるだけの情報があるか（定数より何点よくなるか。"
          "小さいほど形は決められない）")
    print(f"  {'':<10}" + "".join(f"{ch:>8}" for ch in CHARS))
    for mod, fam in [("audio", "")] + [("visual", f) for f in FAMS]:
        lab = "聴覚" if mod == "audio" else LAB[fam]
        r = {x["char"]: x["signal_vs_const"] for x in seltab
             if x["modality"] == mod and x["family"] == fam}
        print(f"  {lab:<12}" + "".join(f"{r[ch]:>8.1f}" for ch in CHARS))

    # =====================================================================
    # 表を作る
    # =====================================================================
    print("\n表を作る")
    sets = {
        "logistic": (FV_log, FA_log,
                     "ロジスティック当てはめ（現行の推定。測った範囲の外へも伸ばす）"),
        "logistic_clamped": (FV_logc, FA_logc,
                             "ロジスティック当てはめ（外挿しない。切り分け用）"),
        "isotonic": (FV_iso, FA_iso,
                     f"単調回帰（袋詰めPAVA 袋{a.bag}・補間{a.interp}・外挿しない）"),
        "selected_bestcv": (FVsel["bestcv"], FAsel["bestcv"],
                            f"字ごとに形を選ぶ（{a.cv_folds}分割交差確認・最小・外挿しない）"),
        "selected_1se": (FVsel["1se"], FAsel["1se"],
                         f"字ごとに形を選ぶ（{a.cv_folds}分割交差確認・1SE則・外挿しない）"),
    }
    built, FVs, FAs, alllog, allwin = {}, {}, {}, [], []
    for tag, (FV, FA, note) in sets.items():
        tables, ranges, log, win = build(FV, FA, levels, tag)
        doc = write_json(os.path.join(a.out, f"transfer_warp_v4_{tag}.json"),
                         tables, ranges, tag, note)
        built[tag] = doc
        FVs[tag], FAs[tag] = FV, FA
        alllog += log
        allwin += win
    pd.DataFrame(alllog).to_csv(os.path.join(a.out, "build_log_v4.csv"), index=False)
    pd.DataFrame(allwin).to_csv(os.path.join(a.out, "composite_window_v4.csv"),
                                index=False)

    # ---- 比較 ----
    ink, bw = glyph_stats(os.path.join(ROOT, "experiment/base"))
    cmp_df = compare(built, FVs, FAs, FV_iso, FA_iso, ink, bw)
    cmp_df.to_csv(os.path.join(a.out, "compare_estimators.csv"), index=False)
    TAGS = list(sets.keys())
    TAGJA = {"logistic": "ロジ(現行)", "logistic_clamped": "ロジ+丸め",
             "isotonic": "単調回帰", "selected_bestcv": "形選択(最良)",
             "selected_1se": "形選択(1SE)"}
    MAIN_ROWS = FAMS_MAIN + ["+".join(PAIR_MAIN)]
    REF_ROWS = FAMS_REF + [x + "+" + y for x, y in PAIRS if (x, y) != PAIR_MAIN]

    def famja(f):
        return "×".join(LAB[x] for x in f.split("+"))

    def show(values, fmt="{:>13.2f}", rows=None):
        rows = rows or (MAIN_ROWS + ["---"] + REF_ROWS)
        print(f"  {'方式':<16}" + "".join(f"{TAGJA[t]:>13}" for t in TAGS))
        for f in rows:
            if f == "---":
                print("  " + "-" * (16 + 13 * len(TAGS)) + "  ↓ 参考(今回落とす方式)")
                continue
            print(f"  {famja(f):<18}" + "".join(fmt.format(values.loc[f, t])
                                                for t in TAGS))

    print("\n" + "=" * 78)
    print("① 進み具合の空間：提案 vs 対照2（一次変換）の平均差 pt［打ち切り窓］")
    print("=" * 78)
    show(cmp_df.pivot_table(index="family", columns="estimator", values="d_b2_gates"))

    print("\n" + "=" * 78)
    print("② 正答率の空間：参加者が受け取る『読める確率』の差 pt（共通の参照曲線）")
    print("   ここが小さいと、提案と対照2は**同じ操作**になっている")
    print("=" * 78)
    show(cmp_df.pivot_table(index="family", columns="estimator", values="acc_d_b2"))

    print("\n" + "=" * 78)
    print("③ 聴覚の目標軌跡をどれだけ再現できたか RMSE pt（小さいほどよい・共通の参照曲線）")
    print("=" * 78)
    for lab, col in (("提案", "rmse_target_proposed"), ("対照2", "rmse_target_b2"),
                     ("★ 提案が対照2より目標に近い差（＝仮説そのもの。大きいほどよい）",
                      "gain_over_b2")):
        print(f"  --- {lab}")
        show(cmp_df.pivot_table(index="family", columns="estimator", values=col))

    print("\n" + "=" * 78)
    print("④ 提案の軌跡を『時間の一次関数』で近似したときの残差／可動域")
    print("   0 に近いほど**一次変換に潰れている**（論文 3.3 節が警告した状態）")
    print("=" * 78)
    show(cmp_df.pivot_table(index="family", columns="estimator",
                            values="affine_resid_rel"), fmt="{:>13.3f}")

    print("\n" + "=" * 78)
    print("⑤ 分解能。上段=提案の道の上に出る別々の絵の総数、"
          "下段=7つの打ち切り時点が何枚に分かれるか（最大7）")
    print("=" * 78)
    show(cmp_df.pivot_table(index="family", columns="estimator",
                            values="n_distinct_images"), fmt="{:>13.0f}")
    print("  --- 7つの打ち切り時点で別々の絵になる数（最大7・小さいと水準が潰れている）")
    show(cmp_df.pivot_table(index="family", columns="estimator",
                            values="n_distinct_at_gates"), fmt="{:>13.1f}")

    print("\n■ 字ごと（主軸2方式＋ぼやけ×端から）の 提案 vs 対照2［正答率pt］")
    for fam in MAIN_ROWS:
        s = cmp_df[cmp_df.family == fam]
        print(f"  {famja(fam)}")
        print(f"    {'字':<4}" + "".join(f"{TAGJA[t]:>13}" for t in TAGS)
              + f"{'形(視覚)':>14}")
        for ch in CHARS:
            g = {t: s[(s.estimator == t) & (s.char == ch)].iloc[0] for t in TAGS}
            kk = g["selected_bestcv"].curve_kind
            print(f"    {ch:<5}" + "".join(f"{g[t].acc_d_b2:>13.2f}" for t in TAGS)
                  + f"{(CAND_JA[kk] if kk else '-'):>14}")

    # ---- 要約 ----
    srows = []
    for tag in TAGS:
        s = cmp_df[cmp_df.estimator == tag]
        for grp, sub in (("主軸(ぼやけ・端から・その組)", s[s.family.isin(MAIN_ROWS)]),
                         ("参考(うすい・点が増える系)", s[s.family.isin(REF_ROWS)]),
                         ("全体", s)):
            srows.append(dict(
                estimator=tag, group=grp, n_cells=len(sub),
                d_b2_gates=sub.d_b2_gates.mean(), d_b1_gates=sub.d_b1_gates.mean(),
                acc_d_b2=sub.acc_d_b2.mean(), acc_d_b1=sub.acc_d_b1.mean(),
                acc_span=sub.acc_span.mean(),
                rmse_target_proposed=sub.rmse_target_proposed.mean(),
                rmse_target_b2=sub.rmse_target_b2.mean(),
                rmse_target_b1=sub.rmse_target_b1.mean(),
                gain_over_b2=sub.gain_over_b2.mean(),
                n_cells_gain_positive=int((sub.gain_over_b2 > 0).sum()),
                rmse_self_proposed=sub.rmse_self_proposed.mean(),
                affine_resid_rel=sub.affine_resid_rel.median(),
                n_distinct_images_median=sub.n_distinct_images.median(),
                n_distinct_at_gates_median=sub.n_distinct_at_gates.median(),
                n_distinct_at_gates_min=sub.n_distinct_at_gates.min(),
                n_distinct_images_min=sub.n_distinct_images.min(),
                span_pt_median=sub.span_pt.median(),
                n_cells_span_under_1pt=int((sub.span_pt < 1.0).sum()),
                n_cells_acc_d_b2_under_5pt=int((sub.acc_d_b2 < 5.0).sum()),
                n_cells_jump_over_25pt=int((sub.n_jump_over_25pt > 0).sum())))
    sdf = pd.DataFrame(srows)
    sdf.to_csv(os.path.join(a.out, "compare_summary.csv"), index=False)

    print("\n" + "=" * 78)
    print("■ 要約（主軸＝ぼやけ・端から・ぼやけ×端から の 24 セル）")
    print("=" * 78)
    m = sdf[sdf.group.str.startswith("主軸")].set_index("estimator")
    print(f"  {'推定':<18}{'①差pt':>8}{'②正答率差':>10}{'③再現(提案)':>12}"
          f"{'③再現(対照2)':>13}{'④直線度':>9}{'⑤枚数':>8}{'不成立':>7}")
    for t in TAGS:
        r = m.loc[t]
        print(f"  {TAGJA[t]:<20}{r.d_b2_gates:>8.2f}{r.acc_d_b2:>10.2f}"
              f"{r.rmse_target_proposed:>12.2f}{r.rmse_target_b2:>13.2f}"
              f"{r.gain_over_b2:>9.2f}{r.affine_resid_rel:>9.3f}{r.n_distinct_at_gates_median:>8.1f}"
              f"{r.n_cells_span_under_1pt:>7}")

    # ---- 補間の目盛りの効き ----
    print("\n補間の目盛り（対数 x / 生の x）の効きを測る")
    irows = []
    for sc in ("log", "linear"):
        FVi = {}
        FAi = {ch: fit_isotonic(Acell[ch], bag=a.bag, seed=a.seed, scale=sc, clamp=True,
                                out_lo=float(Acell[ch].xs.min()),
                                out_hi=float(Acell[ch].xs.max()))[0] for ch in CHARS}
        for fam in FAMS:
            for ch in CHARS:
                FVi[(ch, fam)] = fit_isotonic(Vcell[(ch, fam)], bag=a.bag, seed=a.seed,
                                              scale=sc, clamp=True, out_lo=0.0,
                                              out_hi=100.0)[0]
        tb, rg, lg, wn = build(FVi, FAi, levels, "iso_" + sc)
        doc = {"tables": tb, "composite_map": rg}
        c2 = compare({("iso_" + sc): doc}, {("iso_" + sc): FVi}, {("iso_" + sc): FAi},
                     FV_iso, FA_iso, ink, bw)
        s = c2[c2.family.isin(MAIN_ROWS)]
        irows.append(dict(interp=sc, scope="主軸", d_b2_gates=s.d_b2_gates.mean(),
                          acc_d_b2=s.acc_d_b2.mean(), span_median=s.span_pt.median(),
                          rmse_target_proposed=s.rmse_target_proposed.mean()))
        for _, rr in c2.iterrows():
            irows.append(dict(interp=sc, family=rr.family, char=rr.char,
                              d_b2_gates=rr.d_b2_gates, acc_d_b2=rr.acc_d_b2,
                              span=rr.span_pt))
    pd.DataFrame(irows).to_csv(os.path.join(a.out, "interp_sensitivity.csv"), index=False)
    for r in [x for x in irows if "family" not in x]:
        print(f"  {r['interp']:<8} ①差 {r['d_b2_gates']:.2f}pt  "
              f"②正答率差 {r['acc_d_b2']:.2f}pt  "
              f"③再現 {r['rmse_target_proposed']:.2f}pt")

    # =====================================================================
    # 組み合わせで、単体の弱点（分解能）が解けるか
    # =====================================================================
    print("\n" + "=" * 78)
    print("■ 分解能：5〜95% の窓の中で作れる『別々の絵』の枚数")
    print("   ⚠ 組み合わせは **掛け算にならない**。アニメは u を 0→1 と一方向に進む")
    print("     1本の道なので格子の全点は通らず、枚数は両方の段の**足し算**になる。")
    print("=" * 78)
    doc = built["isotonic"]
    cmapd = doc["composite_map"]
    us = np.linspace(0.0, 100.0, 50001)
    rrows = []
    for fam in FAMS:
        for ch in CHARS:
            w = FV_iso[(ch, fam)].window(*levels[fam])
            ss = np.linspace(w[2], w[3], 50001)
            try:
                nd = n_distinct(quant_levels(fam, ch, ss, ink, bw))
                nd2 = n_distinct(quant_levels(fam, ch, ss, ink, bw, blur_px_step=0.01))
            except Exception:
                nd = nd2 = float("nan")
            rrows.append(dict(kind="single", family=fam, char=ch, s5=w[2], s95=w[3],
                              n_distinct=nd, n_distinct_blur001=nd2,
                              n_a=nd, n_b=float("nan")))
    for fa, fb in PAIRS:
        key = fa + "+" + fb
        for ch in CHARS:
            m = cmapd[key][ch]
            idx = np.clip(us / 100.0, 0, 1) * (N_MAP - 1)
            lo = np.floor(idx).astype(int)
            hi = np.minimum(lo + 1, N_MAP - 1)
            f = idx - lo
            sa = np.array(m["a"])[lo] * (1 - f) + np.array(m["a"])[hi] * f
            sb = np.array(m["b"])[lo] * (1 - f) + np.array(m["b"])[hi] * f
            try:
                la = quant_levels(fa, ch, sa, ink, bw)
                lb = quant_levels(fb, ch, sb, ink, bw)
                rrows.append(dict(kind="composite", family=key, char=ch,
                                  s5=float(min(sa.min(), sb.min())),
                                  s95=float(max(sa.max(), sb.max())),
                                  n_distinct=n_distinct(la, lb),
                                  n_distinct_blur001=n_distinct(
                                      quant_levels(fa, ch, sa, ink, bw, blur_px_step=0.01),
                                      quant_levels(fb, ch, sb, ink, bw, blur_px_step=0.01)),
                                  n_a=n_distinct(la), n_b=n_distinct(lb)))
            except Exception:
                pass
    rdf = pd.DataFrame(rrows)
    rdf.to_csv(os.path.join(a.out, "composite_resolution.csv"), index=False)
    agg = rdf.groupby("family")["n_distinct"].agg(["median", "min", "max"])
    order = FAMS + [x + "+" + y for x, y in PAIRS]
    print(f"  {'方式':<18}{'中央':>7}{'最小':>7}{'最大':>7}   （単体の段数 a / b）")
    for f in order:
        if f not in agg.index:
            continue
        r = agg.loc[f]
        sub = rdf[rdf.family == f]
        ab = ""
        if f in cmapd:
            ab = f"   {sub.n_a.median():.0f} + {sub.n_b.median():.0f}"
        star = "  ←主軸" if f in MAIN_ROWS else ""
        print(f"  {famja(f):<20}{r['median']:>7.0f}{r['min']:>7.0f}{r['max']:>7.0f}"
              + ab + star)

    print(f"\n完了: {os.path.relpath(a.out, ROOT)}")


if __name__ == "__main__":
    main()
