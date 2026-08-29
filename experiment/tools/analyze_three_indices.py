#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
識別の進み方を 3 つの指標で書き直す（到達点 U ／ 中点 T50 ／ 幅 W）
=============================================================================
2026-08-29。外部の助言（独立2件が同じ結論）を受けての方針変更。

■ なにが問題だったか
  「中点に達する時刻をそろえる」という合わせ方を考えていたが、**中点の定義**で詰まった。
  同じ研究室の別論文（かるたの読み上げ）は確信度を 0.5〜1.0 で測り、その中点 0.75 を
  基準にしていた。下限も上限も固定なので、どの刺激でも同じ基準になる。
  ところが今回は**上限が字ごとに違う**。共通の 50% を基準にすると、そこまで届かない字
  （ら・し・が、および打ち切りの範囲では ぱ も）で中点が定義できない。

■ 新しい書き方（1本の曲線を1つの閾値に押し込まない）
  到達点 U … 単調回帰曲線の**終端の値**（最後の水準での推定値）。
              「観測された最大値」ではない。最大値だと、たまたま高く出た1セルを
              拾って上に偏る。論文では "estimated endpoint performance" と書く。
  中点 T50 … 下限 L から到達点 U までの 50% 地点に最初に達する x。
  幅   W   … T75 − T25。「どれくらい急に／緩やかに分かるようになるか」。
              ⚠ 傾きを微分で取ってはいけない。単調回帰は階段状なので、微分は
              平らなところで 0、跳ぶところで定義できず、補間の仕方で値が変わる。

    q(x) = ( v(x) − L ) / ( U − L )      T_p = inf{ x : q(x) ≥ p }

    L（下限）= 正答率では**当てずっぽうの水準**  聴覚 1/68 = 0.0147
                                                  視覚 1/72 = 0.0139
               （回答盤の数。transfer_config.js の answer_grid / answer_grid_visual）
             = 情報量では 0（並べ替えで偏りを引いた値なので、届いていなければ 0）

  ⚠「天井の半分」は誤り。正しくは「**当てずっぽうの水準から天井までの半分**」。
  ⚠「50% に届かない字は到達点を使う」という案は採らない。最高 49% の字と 51% の字で
    指標の意味が変わり、異なる量を同じ列に混ぜることになるため。

  参考にした先行の考え方（2026-08-29 に本文を確認したもののみ）:
   ・Schütt, Harmeling, Macke & Wichmann (2016) Vision Research 122:105-123.
       心理測定関数を「閾値 m と幅 w」で表す。m は正規化した曲線が 0.5 になる水準、
       w は 0.05 に達する水準と 0.95 に達する水準の差。著者自身が
       「幅は傾きより意味が取りやすく、どの関数形でも同じ意味になる」と書いている。
       ⚠ ただし彼らの 0.05/0.95 は**guess/lapse で伸縮する前**の曲線の上での値であり、
         観測正答率の 5%/95% とは一致しない（論文中に明記あり）。W = T75 − T25 は
         「幅で急峻さを表す」という発想が同じなだけで、パーセンタイルも基準面も違う。
   ・psignifit の閾値は既定で「2つの漸近線のちょうど中間」（threshPC = 0.5）。
       ＝ 当てずっぽうの水準と天井の中点。今回の T50 と同じ立て方。
   ・Marino, Jamal & Zito, "Pharmacodynamics", StatPearls (NBK507791).
       Emax ＝ 薬の最大効果、EC50 ＝ 最大効果の半分を出す濃度。
       ⚠ この出典にはベースライン E0 の記述はない。「E0 から Emax までの半分」という
         書き方をこの出典で支えることはできない。

■ 出さない数字（大事）
  1) 到達点が当てずっぽうと区別できない字 … T50・W を**推定不能**とする。
     聴覚の「が」がこれ。全部聞かせても正答 2/66 ≒ 3%。当てずっぽうは 1.5%。
     68 試行ではこの差は検出できない（2/68 の 95% 信頼区間はおよそ 0.4〜10%）。
     その間の「中点」を計算しても意味を持たない。**研究からは除外しない。**
     情報量ベースでは通常どおり扱う（「か」に集中する＝情報は届いている）。
  2) 測った範囲の外に出るもの … 左打ち切り／右打ち切りとして扱い、**外挿しない**。
     いちばん短い打ち切り（10ms）や、いちばん薄い水準ですでに p を超えていれば
     「T_p < 10ms」とだけ書く。
  3) T25 と T75 が**同じ1区間の中**に入るもの … W は測れていない（水準の刻みより
     細かい値を、直線補間が作っているだけ）。「1区間未満」として推定不能にする。
  4) 8 字すべてに数字を出そうとしない。

■ 曲線の推定（既存のものを再利用。新しく作らない）
  ・単調回帰＝袋詰め PAVA。build_warp_b4.pava をそのまま使う。
  ・情報量は analyze_information.py が採った ③ **相互情報量の字ごとの分け前**

        D_c(x) = KL( P(R|c,x) ‖ P(R|x) )
               = Σ_r P(r|c,x) · log2[ P(r|c,x) / P(r|x) ]        [bit]
        I(S;R|x) = Σ_c P(c|x) · D_c(x)

    R は参加者が回答盤で選んだ字（聴覚 68 択・視覚 72 択）、S は出した字（本命 8 字）。
    P(R|x) は**その水準の実測の周辺分布**。基準が実測なので、何も届いていないときの
    回答の偏り（人の事前分布）は自動的に差し引かれ、届いていなければ 0 になる。
    有限標本の上向きの偏りは、水準の中で字ラベルだけを入れ替える並べ替えの平均を
    引いて補正する。上限は H(S) = log2(8) = 3 bit。
    ⚠ この量の名前は文献では **stimulus-specific surprise（specific surprise）**。
      Bezzi, M. (2007) "Quantifying the information transmitted in a single stimulus",
      BioSystems 89(1-3):4-9 が、刺激ごとの情報量には4つの定義があると整理し、
      この KL 型を I₁ = specific surprise（起源は Fano）として挙げ、
      Σ_s p(s)·I₁(s) = I(S;R) になることを明記している。
      ⚠ Butts (2003) の "stimulus-specific information (SSI)" は**別の量**
        （SSI(s) = Σ_r p(r|s)[H(S) − H(S|r)]）。混同しないこと。
  ・前提は build_warp_b4.py / analyze_information.py と同一
    （2 バッチ統合・ぼやけは WebKit 除外・点が増えるは 300ms 限定・外挿しない）。

■ 信頼区間（入れ子ブートストラップ）
  点推定は「袋詰め PAVA でならした曲線」から取る。そのばらつきを測るには、
  **袋詰めまで込みで**やり直す必要がある（袋詰めは推定手続きの一部だから）。
    外側 … 参加者を復元抽出して1組の標本を作る
    内側 … その標本の中で袋詰め PAVA をやり直し、曲線を作る
    → その曲線から 3 指標を計算する。これを R 回くり返して 2.5/97.5 パーセンタイル。
  袋の中で打ち切りになった回の割合も出す（区間が信用できるかの目安）。

■ 副次指標（意味が違うので別の表にする）
  「共通の 50% 正答率に達する x」。届く字についてだけ出す。
    相対中点 T50 … その字自身の識別過程がいつ半分進んだか
    絶対 50%    … 人の半数が実際に正しく答えられる状態になったのはいつか

■ 出力（project/data_calib2_live/analysis_three_indices/）
  three_indices.csv        全 80 行（正答率/情報量 × 聴覚8 + 視覚4方式×8）
  three_indices_audio.csv  聴覚だけを読みやすく並べたもの
  three_indices_visual.csv 視覚だけを読みやすく並べたもの
  absolute50.csv           副次指標（共通の 50% 正答率に達する x）
  audio_full_reference.csv 参考: 聴覚を打ち切らずに全部聞かせたときの正答率・情報量
  curve_check.csv          curves_info.csv と一致しているかの検算
  not_estimable.csv        推定不能になったセルと、その理由
  tables.txt               人が読む表（そのまま貼れる形）

使い方:
    python3 experiment/tools/analyze_three_indices.py            # 約5〜8分
    python3 experiment/tools/analyze_three_indices.py --boot 50  # 動作確認用（速い）

本番ファイル（experiment/transfer_warp.json / transfer_config.js / transfer.js）には
**書かない**。読むだけ。
"""
import argparse
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_warp_b4 as B4          # noqa: E402  pava / 定数
import analyze_information as AI    # noqa: E402  情報量の道具・読み込み

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHARS = B4.CHARS
FAMS = B4.FAMS
LAB = B4.LAB
GATES_MS = B4.GATES_MS

N_CHOICES_AUDIO = len(AI.ANS_AUDIO)     # 68
N_CHOICES_VISUAL = len(AI.ANS_VISUAL)   # 72
L_ACC_AUDIO = 1.0 / N_CHOICES_AUDIO
L_ACC_VISUAL = 1.0 / N_CHOICES_VISUAL
PS = (0.25, 0.50, 0.75)
ORDER = ["か", "あ", "つ", "ま", "ぱ", "ら", "し", "が"]   # 全長正答率の高い順


# ===========================================================================
# 曲線から 3 指標を取り出す
# ===========================================================================
def t_at(xs, ys, L, U, p, logx=True):
    """q(x) = (v(x)−L)/(U−L) が p に達する最小の x。

    戻り値 dict:
      value      … 推定値（推定できないときは None）
      status     … "ok" / "censored_low" / "degenerate"
      lo_x, hi_x … その値をはさむ実測水準（補間の効いている区間＝分解能の限界）
      seg        … その区間の番号（W が1区間に収まっているかの判定に使う）
    """
    xs = np.asarray(xs, float)
    ys = np.asarray(ys, float)
    if not np.isfinite(U) or (U - L) <= 1e-12:
        return dict(value=None, status="degenerate", lo_x=None, hi_x=None, seg=None)
    q = (ys - L) / (U - L)
    if q[0] >= p - 1e-12:
        # いちばん小さい水準ですでに超えている＝測った範囲より前（左打ち切り）
        return dict(value=None, status="censored_low", lo_x=None,
                    hi_x=float(xs[0]), seg=-1)
    j = int(np.searchsorted(q, p, side="left"))
    j = min(max(j, 1), len(q) - 1)
    q0, q1 = q[j - 1], q[j]
    tx = np.log(np.maximum(xs, 1e-9)) if logx else xs
    if q1 - q0 <= 1e-12:
        t = tx[j]
    else:
        t = tx[j - 1] + (p - q0) / (q1 - q0) * (tx[j] - tx[j - 1])
    x = math.exp(t) if logx else t
    return dict(value=float(np.clip(x, xs[0], xs[-1])), status="ok",
                lo_x=float(xs[j - 1]), hi_x=float(xs[j]), seg=j)


def indices_from_curve(xs, ys, L, logx=True):
    """1 本の曲線から U / T25 / T50 / T75 / W を出す。"""
    ys = np.maximum.accumulate(np.asarray(ys, float))
    U = float(ys[-1])
    out = dict(U=U, bottom=float(ys[0]))
    for p in PS:
        r = t_at(xs, ys, L, U, p, logx=logx)
        tag = f"T{int(round(p * 100))}"
        out[tag] = r["value"]
        out[tag + "_status"] = r["status"]
        out[tag + "_lo_x"] = r["lo_x"]
        out[tag + "_hi_x"] = r["hi_x"]
        out[tag + "_seg"] = r["seg"]
    if out["T25_status"] != "ok" or out["T75_status"] != "ok":
        out["W"] = None
        out["W_status"] = ("degenerate"
                           if "degenerate" in (out["T25_status"], out["T75_status"])
                           else "censored")
    elif out["T25_seg"] == out["T75_seg"]:
        # 25% 点と 75% 点が同じ1区間の中＝水準の刻みより細かいことは測れていない
        out["W"] = None
        out["W_status"] = "within_one_step"
    else:
        out["W"] = float(out["T75"] - out["T25"])
        out["W_status"] = "ok"
    return out


def beta_equiv(w):
    """ロジスティック q(t)=1/(1+exp[−β(t−T50)]) を仮定したときの β 相当。
    T75 − T25 = 2·ln3/β なので β = 2·ln3 / W。論文では W をそのまま報告する。"""
    if w is None or not np.isfinite(w) or w <= 0:
        return None
    return float(2.0 * math.log(3.0) / w)


# ===========================================================================
# 袋詰め PAVA（analyze_information.py と同じ手続き）
#   pool … 袋詰めのもとになる参加者の並び。外側ブートストラップではここに
#          復元抽出した参加者を渡す（＝入れ子ブートストラップ）。
# ===========================================================================
def bagged_info_curve(dat, rng, pool, bag, perm_per_bag):
    """情報量 D_c の袋詰め PAVA。(nc, nl) の単調曲線を返す。"""
    n = len(pool)
    draws = np.zeros((bag, dat.nc, dat.nl))
    for b in range(bag):
        pick = pool[rng.integers(0, n, size=n)]
        rows = np.concatenate([dat.rows_by_pid[i] for i in pick])
        Cb = dat.counts(rows=rows)
        Db, _, ncj_b, _ = AI.info_from_counts(Cb)
        an = np.zeros_like(Db)
        for _ in range(perm_per_bag):
            cb = dat.perm_chars(rng, rows=rows)
            Cbp = AI.counts_from_index(cb, dat.ji[rows], dat.ri[rows],
                                       dat.nc, dat.nl, dat.nr)
            Dbp, _, _, _ = AI.info_from_counts(Cbp)
            an += Dbp
        Db = Db - an / perm_per_bag
        for c in range(dat.nc):
            draws[b, c] = B4.pava(Db[c], np.maximum(ncj_b[c], 1e-9))
    return np.maximum.accumulate(np.maximum(draws.mean(axis=0), 0.0), axis=1)


def bagged_acc_curve(dat, rng, pool, bag):
    """正答率の袋詰め PAVA。(nc, nl) の単調曲線を返す。"""
    n = len(pool)
    acc = np.zeros((dat.nc, dat.nl))
    for _ in range(bag):
        pick = pool[rng.integers(0, n, size=n)]
        rows = np.concatenate([dat.rows_by_pid[i] for i in pick])
        k, nn = dat.acc_by_level(rows)
        for c in range(dat.nc):
            acc[c] += B4.pava(k[c] / np.maximum(nn[c], 1.0), np.maximum(nn[c], 1e-9))
    return np.maximum.accumulate(acc / bag, axis=1)


def estimate(dat, kind, bag_pt, ppb_pt, boot, bag_in, ppb_in, seed, label=""):
    """点推定の曲線と、入れ子ブートストラップの曲線束を返す。

    戻り値: (curve_pt (nc,nl), curves_boot (boot,nc,nl))
    """
    P = len(dat.pids)
    pool = np.arange(P)
    rng = np.random.default_rng(seed)
    t0 = time.time()
    if kind == "info":
        pt = bagged_info_curve(dat, rng, pool, bag_pt, ppb_pt)
    else:
        pt = bagged_acc_curve(dat, rng, pool, bag_pt)
    reps = np.zeros((boot, dat.nc, dat.nl))
    for r in range(boot):
        outer = rng.integers(0, P, size=P)          # 参加者の復元抽出
        if kind == "info":
            reps[r] = bagged_info_curve(dat, rng, outer, bag_in, ppb_in)
        else:
            reps[r] = bagged_acc_curve(dat, rng, outer, bag_in)
    print(f"    {label:<12} {kind:<4} 点推定(袋{bag_pt}) + 入れ子{boot}回×袋{bag_in}"
          f"  … {time.time() - t0:.1f}s")
    return pt, reps


# ===========================================================================
# 1 セル分の集計
# ===========================================================================
def summarize_cell(xs, y_point, y_reps, L, logx=True, w_min_ok=0.90):
    """点推定と、参加者を取り直した曲線の束から 3 指標と 95% 区間を作る。

    打ち切りの扱い（ここが肝）
      T_p … 取り直した回で左打ち切りになったら、その回の値を「測った範囲の下端」で
             置き換える。真の T_p はそれより小さいので、これは**下向きの下限**であり、
             区間の下端が下限に張り付いたら「≤ 下端」と読めばよい。点推定は必ず
             区間の中に入る。
      W  … 置き換えができない。T25 が範囲の外なら W は「T75 − （範囲の外の値）」で
             **いくらでも大きくなりうる**（上に非有界）。だから
             「取り直した回の {w_min_ok:.0%} 以上で幅が測れた」ときだけ区間を出し、
             そうでなければ**推定不能**とする。
             ⚠ 落とした回を無視して残りだけでパーセンタイルを取ると、点推定が区間の
               外に出る（実際に最初の実装でそうなった）。
    """
    pt = indices_from_curve(xs, y_point, L, logx=logx)
    nb = y_reps.shape[0]
    x_min = float(np.asarray(xs, float)[0])
    Us = []
    Ts = {f"T{int(round(p*100))}": [] for p in PS}
    cens = {f"T{int(round(p*100))}": 0 for p in PS}
    Ws, w_cens, w_onestep = [], 0, 0
    for b in range(nb):
        r = indices_from_curve(xs, y_reps[b], L, logx=logx)
        Us.append(r["U"])
        for p in PS:
            tag = f"T{int(round(p*100))}"
            if r[tag + "_status"] == "ok":
                Ts[tag].append(r[tag])
            elif r[tag + "_status"] == "censored_low":
                Ts[tag].append(x_min)      # 下限で置き換え（真の値はこれ以下）
                cens[tag] += 1
            else:
                cens[tag] += 1
        if r["W_status"] == "ok":
            Ws.append(r["W"])
        else:
            w_cens += 1
            if r["W_status"] == "within_one_step":
                w_onestep += 1
    out = dict(pt)
    Us = np.asarray(Us, float)
    out["U_lo"] = float(np.percentile(Us, 2.5))
    out["U_hi"] = float(np.percentile(Us, 97.5))
    out["U_above_L"] = bool(out["U_lo"] > L)
    for p in PS:
        tag = f"T{int(round(p*100))}"
        v = np.asarray(Ts[tag], float)
        fc = cens[tag] / nb
        out[tag + "_frac_censored_bags"] = fc
        # 打ち切りが 10% 未満のときだけ区間を出す。
        #   10〜50% … 点推定は残すが区間は作らない（打ち切りの塊が入るとパーセンタイルが
        #             点推定を挟まなくなる。実際に最初の実装でそうなった）
        #   50% 以上 … 測定範囲の下端より前に出るのが普通なので**推定不能**
        if fc < 0.10 and len(v) >= 20:
            out[tag + "_lo"] = float(np.percentile(v, 2.5))
            out[tag + "_hi"] = float(np.percentile(v, 97.5))
        else:
            out[tag + "_lo"] = out[tag + "_hi"] = None
        out[tag + "_lo_is_bound"] = bool(
            out[tag + "_lo"] is not None and abs(out[tag + "_lo"] - x_min) < 1e-9)
        if fc >= 0.50 and out[tag + "_status"] == "ok":
            out[tag] = None
            out[tag + "_status"] = "unstable_censored"
    W = np.asarray(Ws, float)
    frac_ok = len(W) / nb
    out["W_frac_unusable_bags"] = w_cens / nb
    out["W_frac_within_one_step_bags"] = w_onestep / nb
    if frac_ok >= w_min_ok and len(W) >= 20:
        out["W_lo"] = float(np.percentile(W, 2.5))
        out["W_hi"] = float(np.percentile(W, 97.5))
    else:
        out["W_lo"] = out["W_hi"] = None
        if out["W_status"] == "ok":
            # 点推定は出せても、取り直すと測れなくなる＝測定範囲・刻みが足りない
            out["W"] = None
            out["W_status"] = ("unstable_censored"
                               if w_cens - w_onestep >= w_onestep
                               else "unstable_onestep")
    out["W_frac_ok_bags"] = frac_ok
    out["n_boot"] = nb
    return out


def reason_ja(rec, L, target):
    """推定不能の理由を日本語 1 行で。"""
    if not rec["U_above_L"]:
        base = "当てずっぽうの水準" if target == "acc" else "情報 0"
        return (f"到達点 U={rec['U']:.4g} の95%区間 [{rec['U_lo']:.4g}, {rec['U_hi']:.4g}] が"
                f"{base}（L={L:.4g}）を含む。到達点そのものが下限と区別できないので、"
                "そこまでの途中の点も定義できない")
    parts = []
    for tag in ("T25", "T50", "T75"):
        if rec[tag + "_status"] == "censored_low":
            parts.append(f"いちばん小さい水準（{rec[tag + '_hi_x']:g}）ですでに {tag[1:]}% を"
                         f"超えている＝{tag} は測った範囲より前（{tag} < {rec[tag + '_hi_x']:g}）")
        elif rec[tag + "_status"] == "unstable_censored":
            parts.append(f"参加者を取り直すと {100*rec[tag + '_frac_censored_bags']:.0f}% の回で "
                         f"{tag} が測定範囲より前に出る（測定範囲が下側で足りない）")
    if rec["W_status"] == "within_one_step":
        parts.append(f"25%点と75%点が同じ1区間（{rec['T25_lo_x']:g}〜{rec['T25_hi_x']:g}）の"
                     "中に入る。水準の刻みより細かい幅は測れていない"
                     "（直線補間が作った数字にすぎない）。"
                     f"参加者を取り直すと {100*rec['W_frac_ok_bags']:.0f}% の回でだけ幅が測れた")
    elif rec["W_status"] == "censored":
        parts.append("25%点が測定範囲の外なので幅を引き算できない（W は上に非有界）")
    elif rec["W_status"] == "unstable_censored":
        parts.append("点推定は出せるが、参加者を取り直すと "
                     f"{100*(1-rec['W_frac_ok_bags']):.0f}% の回で 25%点が測定範囲の外に出る"
                     "（そのとき W は上に非有界）。区間が作れないので数値を出さない")
    elif rec["W_status"] == "unstable_onestep":
        parts.append("点推定は出せるが、参加者を取り直すと "
                     f"{100*(1-rec['W_frac_ok_bags']):.0f}% の回で 25%点と 75%点が同じ1区間に"
                     "入ってしまう（水準の刻みが足りない）。区間が作れないので数値を出さない")
    return " ／ ".join(parts) if parts else ""


# ===========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(
        ROOT, "project/data_calib2_live/transfer_trials.csv"))
    ap.add_argument("--out", default=os.path.join(
        ROOT, "project/data_calib2_live/analysis_three_indices"))
    ap.add_argument("--curves", default=os.path.join(
        ROOT, "project/data_calib2_live/analysis_information/curves_info.csv"))
    ap.add_argument("--bag", type=int, default=1000, help="点推定の袋の数")
    ap.add_argument("--ppb", type=int, default=10, help="点推定の袋あたりの並べ替え回数")
    ap.add_argument("--boot", type=int, default=400, help="外側ブートストラップの回数")
    ap.add_argument("--bag-in", type=int, default=120, help="外側1回あたりの内側の袋の数")
    ap.add_argument("--ppb-in", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--interp", choices=["log", "linear"], default="log")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    logx = (a.interp == "log")

    print("=" * 78)
    print("識別の進み方を 3 指標で書き直す（到達点 U ／ 中点 T50 ／ 幅 W）")
    print("=" * 78)
    print(f"  下限 L: 正答率 → 当てずっぽうの水準（聴覚 1/{N_CHOICES_AUDIO}"
          f"={L_ACC_AUDIO:.4f} ／ 視覚 1/{N_CHOICES_VISUAL}={L_ACC_VISUAL:.4f}）"
          "、情報量 → 0 bit")
    print(f"  横軸の補間: {a.interp}（実測水準のあいだだけ。範囲の外へは伸ばさない）")
    print(f"  点推定 袋{a.bag}（並べ替え{a.ppb}/袋）／ "
          f"入れ子ブートストラップ {a.boot}回 × 袋{a.bag_in}（並べ替え{a.ppb_in}/袋）")

    d = AI.load(a.inp)
    vmain, vdecoy, amain, adecoy, afull_all = AI.slices(d)

    # ---------------- 聴覚 ----------------
    lad = amain[~amain["is_embedded_full"]].copy()
    gi = []
    for r in lad.itertuples():
        g = GATES_MS.get(r.target_char, GATES_MS["_default"])
        gi.append(int(np.argmin(np.abs(np.array(g, float) - float(r.gate_ms_f)))))
    lad["gate_index"] = gi
    A = AI.InfoData(lad, "gate_index", AI.ANS_AUDIO, "audio",
                    level_values=np.arange(7, dtype=float))
    print(f"\n[推定] 聴覚 {A.n_trials}試行 / {len(A.pids)}人 / 打ち切り7点")
    D_A, D_A_b = estimate(A, "info", a.bag, a.ppb, a.boot, a.bag_in, a.ppb_in,
                          a.seed, "聴覚")
    acc_A, acc_A_b = estimate(A, "acc", a.bag, a.ppb, a.boot, a.bag_in, a.ppb_in,
                              a.seed + 1, "聴覚")

    # ---------------- 視覚 ----------------
    V, D_V, D_V_b, acc_V, acc_V_b = {}, {}, {}, {}, {}
    for i, fam in enumerate(FAMS):
        s = AI.visual_rows(vmain, fam)
        V[fam] = AI.InfoData(s, "actual_s_pct", AI.ANS_VISUAL, fam)
        print(f"\n[推定] {LAB[fam]} {V[fam].n_trials}試行 / {len(V[fam].pids)}人 "
              f"/ 水準{V[fam].nl}点")
        D_V[fam], D_V_b[fam] = estimate(V[fam], "info", a.bag, a.ppb, a.boot,
                                        a.bag_in, a.ppb_in, a.seed + 10 + i, LAB[fam])
        acc_V[fam], acc_V_b[fam] = estimate(V[fam], "acc", a.bag, a.ppb, a.boot,
                                            a.bag_in, a.ppb_in, a.seed + 20 + i, LAB[fam])

    # ---------------- 既存の曲線との検算 ----------------
    if os.path.exists(a.curves):
        cur = pd.read_csv(a.curves)
        chk = []
        for _, r in cur.iterrows():
            ys_ref = np.array([float(v) for v in str(r["ys"]).split("|")])
            if r["modality"] == "audio":
                arr = D_A if r["target"] == "info" else acc_A
            else:
                arr = D_V[r["family"]] if r["target"] == "info" else acc_V[r["family"]]
            ys_new = arr[CHARS.index(r["char"])]
            if len(ys_new) != len(ys_ref):
                continue
            chk.append(dict(target=r["target"], modality=r["modality"],
                            family=r["family"], char=r["char"],
                            max_abs_diff=float(np.max(np.abs(ys_new - ys_ref))),
                            endpoint_ref=float(ys_ref[-1]), endpoint_new=float(ys_new[-1]),
                            endpoint_diff=float(ys_new[-1] - ys_ref[-1])))
        cdf = pd.DataFrame(chk)
        cdf.to_csv(os.path.join(a.out, "curve_check.csv"), index=False)
        ci, ca = cdf[cdf.target == "info"], cdf[cdf.target == "acc"]
        print(f"\n[検算] analysis_information/curves_info.csv（袋400）との差")
        print(f"  情報量: 曲線全体 最大 {ci['max_abs_diff'].max():.4f} bit ／ "
              f"終端 U の差 最大 {ci['endpoint_diff'].abs().max():.4f} bit")
        print(f"  正答率: 曲線全体 最大 {ca['max_abs_diff'].max()*100:.2f} pt ／ "
              f"終端 U の差 最大 {ca['endpoint_diff'].abs().max()*100:.2f} pt")
        print("  （推定法は同一。袋と並べ替えの回数だけが違う＝乱数のばらつきの範囲）")

    # ---------------- 3 指標 ----------------
    cells = []
    for c, ch in enumerate(CHARS):
        g = np.array(GATES_MS.get(ch, GATES_MS["_default"]), float)
        cells.append(("acc", "audio", "", ch, g, acc_A[c], acc_A_b[:, c, :],
                      L_ACC_AUDIO, "ms", "正答率"))
        cells.append(("info", "audio", "", ch, g, D_A[c], D_A_b[:, c, :],
                      0.0, "ms", "bit"))
    for fam in FAMS:
        xs = V[fam].levels
        for c, ch in enumerate(CHARS):
            cells.append(("acc", "visual", fam, ch, xs, acc_V[fam][c],
                          acc_V_b[fam][:, c, :], L_ACC_VISUAL, "%", "正答率"))
            cells.append(("info", "visual", fam, ch, xs, D_V[fam][c],
                          D_V_b[fam][:, c, :], 0.0, "%", "bit"))

    n_map = {}
    CA_cnt = A.counts()
    for c, ch in enumerate(CHARS):
        n_map[("audio", "", ch)] = int(CA_cnt[c].sum())
    for fam in FAMS:
        Cf = V[fam].counts()
        for c, ch in enumerate(CHARS):
            n_map[("visual", fam, ch)] = int(Cf[c].sum())

    rows, ne_rows = [], []
    for target, modality, fam, ch, xs, ypt, ydr, L, xunit, yunit in cells:
        rec = summarize_cell(xs, ypt, ydr, L, logx=logx)
        est_ok = rec["U_above_L"]
        if not est_ok:
            for tag in ("T25", "T50", "T75"):
                rec[tag] = None
                rec[tag + "_status"] = "degenerate"
                rec[tag + "_lo"] = rec[tag + "_hi"] = None
            rec["W"] = None
            rec["W_status"] = "degenerate"
            rec["W_lo"] = rec["W_hi"] = None
        reason = reason_ja(rec, L, target)
        row = dict(
            target=target, target_unit=yunit, modality=modality, family=fam,
            family_ja=(LAB.get(fam, "") if fam else "聴覚"), char=ch,
            n_trials=n_map[(modality, fam, ch)],
            x_unit=xunit, x_min=float(xs[0]), x_max=float(xs[-1]), n_levels=len(xs),
            L=L, U=rec["U"], U_lo=rec["U_lo"], U_hi=rec["U_hi"],
            U_distinguishable_from_L=est_ok, bottom=rec["bottom"],
            q_at_x_min=((rec["bottom"] - L) / (rec["U"] - L)
                        if rec["U"] - L > 1e-12 else float("nan")))
        for tag in ("T25", "T50", "T75"):
            row[tag] = rec[tag]
            row[tag + "_lo"] = rec.get(tag + "_lo")
            row[tag + "_hi"] = rec.get(tag + "_hi")
            row[tag + "_status"] = rec[tag + "_status"]
            row[tag + "_bracket_lo"] = rec[tag + "_lo_x"]
            row[tag + "_bracket_hi"] = rec[tag + "_hi_x"]
            row[tag + "_frac_censored_boot"] = rec[tag + "_frac_censored_bags"]
            row[tag + "_lo_is_bound"] = rec.get(tag + "_lo_is_bound", False)
        row.update(W=rec["W"], W_lo=rec.get("W_lo"), W_hi=rec.get("W_hi"),
                   W_status=rec["W_status"], beta_equiv=beta_equiv(rec["W"]),
                   W_frac_ok_boot=rec["W_frac_ok_bags"],
                   W_frac_unusable_boot=rec["W_frac_unusable_bags"],
                   W_frac_within_one_step_boot=rec["W_frac_within_one_step_bags"],
                   n_boot=rec["n_boot"], reason=reason)
        rows.append(row)
        if (row["T50_status"] != "ok") or (row["W_status"] != "ok"):
            ne_rows.append(dict(
                target=target, target_ja=("正答率" if target == "acc" else "情報量"),
                modality=modality, family_ja=row["family_ja"], char=ch,
                T50_status=row["T50_status"], W_status=row["W_status"],
                U=row["U"], U_lo=row["U_lo"], U_hi=row["U_hi"], L=L,
                q_at_x_min=row["q_at_x_min"], x_min=row["x_min"], x_unit=xunit,
                reason=reason))

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(a.out, "three_indices.csv"), index=False)
    ned = pd.DataFrame(ne_rows)
    ned.to_csv(os.path.join(a.out, "not_estimable.csv"), index=False)

    # ---------------- 副次指標: 共通の 50% 正答率 ----------------
    ab = []
    for target, modality, fam, ch, xs, ypt, ydr, L, xunit, yunit in cells:
        if target != "acc":
            continue
        ys = np.maximum.accumulate(np.asarray(ypt, float))
        base = dict(modality=modality,
                    family_ja=(LAB.get(fam, "") if fam else "聴覚"), char=ch,
                    x_unit=xunit, endpoint=float(ys[-1]))
        if ys[-1] < 0.5:
            ab.append(dict(base, x_abs50=None, x_abs50_lo=None, x_abs50_hi=None,
                           status="未到達（右打ち切り）",
                           note=(f"測った範囲の端（{xs[-1]:g}{xunit}）でも {ys[-1]*100:.1f}% "
                                 "で 50% に届かない。外挿しない")))
            continue
        r = t_at(xs, ys, 0.0, 1.0, 0.5, logx=logx)   # L=0, U=1 → 絶対 50%
        vals = []
        for b in range(ydr.shape[0]):
            yb = np.maximum.accumulate(ydr[b])
            if yb[-1] < 0.5:
                continue
            rb = t_at(xs, yb, 0.0, 1.0, 0.5, logx=logx)
            if rb["status"] == "ok":
                vals.append(rb["value"])
        vals = np.asarray(vals, float)
        nb = ydr.shape[0]
        frac_fail = (nb - len(vals)) / nb
        # 3 指標と同じ基準: 参加者を取り直して 10% 以上の回で 50% に届かなければ
        # 「届くとは言えない」＝推定不能とする
        okv = frac_fail < 0.10 and len(vals) >= 20
        ab.append(dict(base,
                       x_abs50=(r["value"] if okv else None),
                       x_abs50_lo=(float(np.percentile(vals, 2.5)) if okv else None),
                       x_abs50_hi=(float(np.percentile(vals, 97.5)) if okv else None),
                       status=("ok" if okv else "推定不能（再抽出で届かない回がある）"),
                       note=(f"{nb}回のうち{nb-len(vals)}回（{100*frac_fail:.0f}%）は 50% に"
                             f"届かなかった。点推定は {r['value']:.2f}"
                             if frac_fail > 0 else "")))
    abd = pd.DataFrame(ab)
    abd.to_csv(os.path.join(a.out, "absolute50.csv"), index=False)

    # ---------------- 参考: 聴覚 打ち切りなし ----------------
    # ⚠ analyze_information.slices() が返す afull_all は、出題前の「聞き取り確認」
    #    （check_kind が入っている行）まで拾ってしまう（字あたり 56〜68 行になる）。
    #    ここでは本課題の中に埋め込んだ全長提示だけを使う（字あたり 33〜35 行・計 270 行）。
    #    → analyze_information.py の「打ち切りなし」の参照値は同じ理由でずれている。
    full = amain[amain["is_embedded_full"]
                 & amain["response_char"].notna()
                 & (amain["response_char"] != "-")].copy()
    full["lv0"] = 0.0
    AF = AI.InfoData(full, "lv0", AI.ANS_AUDIO, "audio_full", level_values=[0.0])
    rngF = np.random.default_rng(a.seed + 99)
    CF = AF.counts()
    DF_raw, _, _, _ = AI.info_from_counts(CF)
    accum = np.zeros_like(DF_raw)
    NP = 1000
    for _ in range(NP):
        Cp = AF.counts(ci=AF.perm_chars(rngF))
        Dp, _, _, _ = AI.info_from_counts(Cp)
        accum += Dp
    DF = DF_raw - accum / NP
    kF, nF = AF.acc_by_level()
    fr = []
    for c, ch in enumerate(CHARS):
        n = int(nF[c, 0])
        k = int(kF[c, 0])
        # 二項の 95% 信頼区間（Wilson）
        if n > 0:
            ph = k / n
            z = 1.959964
            den = 1 + z * z / n
            cen = (ph + z * z / (2 * n)) / den
            half = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
            lo, hi = max(0.0, cen - half), min(1.0, cen + half)
        else:
            ph = lo = hi = float("nan")
        sub = full[full["target_char"] == ch]
        from collections import Counter
        cc = Counter(sub["response_char"])
        tp = cc.most_common(2)
        fr.append(dict(char=ch, n_trials=n, n_correct=k, accuracy=ph,
                       acc_lo_wilson=lo, acc_hi_wilson=hi,
                       chance=L_ACC_AUDIO,
                       above_chance=bool(lo > L_ACC_AUDIO),
                       bits_specific_surprise=float(DF[c, 0]),
                       top1=tp[0][0] if tp else "", top1_n=tp[0][1] if tp else 0,
                       top2=tp[1][0] if len(tp) > 1 else "",
                       top2_n=tp[1][1] if len(tp) > 1 else 0,
                       n_distinct_responses=len(cc)))
    fdf = pd.DataFrame(fr)
    fdf.to_csv(os.path.join(a.out, "audio_full_reference.csv"), index=False)

    # =====================================================================
    # 読みやすい表
    # =====================================================================
    lines = []

    def P(s=""):
        print(s)
        lines.append(s)

    def cT(r, tag):
        st = r[tag + "_status"]
        fc = r.get(tag + "_frac_censored_boot", 0.0) or 0.0
        if st == "degenerate":
            return "推定不能"
        if st == "censored_low":
            return f"< {r[tag + '_bracket_hi']:g}"
        if st == "unstable_censored":
            return f"推定不能（再抽出の{100*fc:.0f}%で範囲外）"
        nd = 1 if r["x_unit"] == "ms" else 2
        v = f"{r[tag]:.{nd}f}"
        lo, hi = r.get(tag + "_lo"), r.get(tag + "_hi")
        if lo is not None and np.isfinite(lo):
            lab = f"≤{lo:.{nd}f}" if r.get(tag + "_lo_is_bound") else f"{lo:.{nd}f}"
            v += f" [{lab}, {hi:.{nd}f}]"
        else:
            v += f" ※区間なし(再抽出の{100*fc:.0f}%で範囲外)"
        return v

    def cW(r):
        st = r["W_status"]
        if st == "degenerate":
            return "推定不能（到達点が下限と区別不能）"
        if st == "censored":
            return "推定不能（25%点が範囲外）"
        if st == "within_one_step":
            return "推定不能（1区間の中）"
        if st == "unstable_censored":
            return f"推定不能（再抽出の{100*(1-r['W_frac_ok_boot']):.0f}%で範囲外）"
        if st == "unstable_onestep":
            return f"推定不能（再抽出の{100*(1-r['W_frac_ok_boot']):.0f}%で1区間の中）"
        nd = 1 if r["x_unit"] == "ms" else 2
        v = f"{r['W']:.{nd}f}"
        if r["W_lo"] is not None and np.isfinite(r["W_lo"]):
            v += f" [{r['W_lo']:.{nd}f}, {r['W_hi']:.{nd}f}]"
        return v

    def cU(r):
        if r["target"] == "acc":
            s = f"{r['U']*100:.1f}% [{r['U_lo']*100:.1f}, {r['U_hi']*100:.1f}]"
        else:
            s = f"{r['U']:.2f} [{r['U_lo']:.2f}, {r['U_hi']:.2f}]"
        if not r["U_distinguishable_from_L"]:
            s += " ※下限と区別不能"
        return s

    def pad(s, w):
        """全角を 2 幅として数えて左詰め。"""
        wid = sum(2 if ord(c) > 0x2E80 else 1 for c in s)
        return s + " " * max(1, w - wid)

    P()
    P("=" * 116)
    P("表1. 聴覚：音声を途中で打ち切ったときの識別の進み方。横軸＝音声の長さ [ms]")
    P(f"     [ ] は95%信頼区間（参加者 {len(A.pids)}人の入れ子ブートストラップ {a.boot}回）")
    P("=" * 116)
    for target, unit, note in (
            ("acc", "正答率", "下限 L ＝ 当てずっぽう 1/68 ＝ 1.47%"),
            ("info", "情報量 [bit]", "下限 L ＝ 0 bit（8字なので上限は 3 bit）")):
        P(f"\n--- 縦軸 {unit}（{note}）---")
        P(pad("字", 4) + pad("試行", 6) + pad("到達点 U", 30) + pad("中点 T50", 24)
          + pad("T50をはさむ実測点", 20)
          + pad("幅 W ＝ T75−T25", 44) + pad("25%点", 22) + pad("75%点", 22))
        for ch in ORDER:
            r = df[(df.target == target) & (df.modality == "audio")
                   & (df.char == ch)].iloc[0].to_dict()
            br = ("―" if r["T50_status"] != "ok"
                  else f"{r['T50_bracket_lo']:g}〜{r['T50_bracket_hi']:g}ms")
            P(pad(ch, 4) + pad(str(r["n_trials"]), 6) + pad(cU(r), 30)
              + pad(cT(r, "T50"), 24) + pad(br, 20) + pad(cW(r), 44)
              + pad(cT(r, "T25"), 22) + pad(cT(r, "T75"), 22))
    P()
    P("=" * 116)
    P("表2. 視覚：文字アニメーションを途中で止めたときの識別の進み方。横軸＝進み具合 s [%]")
    P(f"     [ ] は95%信頼区間（入れ子ブートストラップ {a.boot}回）")
    P("=" * 116)
    for target, unit, note in (
            ("acc", "正答率", "下限 L ＝ 当てずっぽう 1/72 ＝ 1.39%"),
            ("info", "情報量 [bit]", "下限 L ＝ 0 bit（8字なので上限は 3 bit）")):
        P(f"\n--- 縦軸 {unit}（{note}）---")
        for fam in FAMS:
            P(f"\n  【{LAB[fam]}】 {V[fam].n_trials}試行 / {len(V[fam].pids)}人 / 水準 "
              + " ・ ".join(f"{x:g}" for x in V[fam].levels) + " %")
            P("  " + pad("字", 4) + pad("試行", 6) + pad("到達点 U", 30)
              + pad("中点 T50", 24) + pad("T50をはさむ実測点", 18)
              + pad("幅 W", 44) + pad("25%点", 22) + pad("75%点", 22))
            for ch in ORDER:
                r = df[(df.target == target) & (df.family == fam)
                       & (df.char == ch)].iloc[0].to_dict()
                br = ("―" if r["T50_status"] != "ok"
                      else f"{r['T50_bracket_lo']:g}〜{r['T50_bracket_hi']:g}%")
                P("  " + pad(ch, 4) + pad(str(r["n_trials"]), 6) + pad(cU(r), 30)
                  + pad(cT(r, "T50"), 24) + pad(br, 18) + pad(cW(r), 44)
                  + pad(cT(r, "T25"), 22) + pad(cT(r, "T75"), 22))

    P()
    P("=" * 116)
    P("表3. 推定不能になったセルと、その理由")
    P("=" * 116)
    if len(ned):
        for _, r in ned.iterrows():
            P(f"\n  ● {r['target_ja']} × {r['family_ja']} × {r['char']}"
              f"   T50={r['T50_status']} / W={r['W_status']}")
            P(f"      {r['reason']}")
    else:
        P("  なし")

    P()
    P("=" * 116)
    P("表4. 副次指標：共通の 50% 正答率に達する x（相対中点 T50 とは意味が違う）")
    P("     相対中点 T50 … その字自身の識別過程がいつ半分進んだか")
    P("     絶対 50%     … 人の半数が実際に正しく答えられる状態になったのはいつか")
    P("=" * 116)
    P(f"\n  【聴覚】横軸 ms")
    for ch in ORDER:
        r = abd[(abd.modality == "audio") & (abd.char == ch)].iloc[0]
        if r["x_abs50"] is None or pd.isna(r["x_abs50"]):
            P(f"  {pad(ch,4)}到達点 {r['endpoint']*100:5.1f}%  → {r['status']}"
              f"  {r['note']}")
        else:
            ci = (f" [{r['x_abs50_lo']:.1f}, {r['x_abs50_hi']:.1f}]"
                  if r["x_abs50_lo"] is not None and not pd.isna(r["x_abs50_lo"]) else "")
            P(f"  {pad(ch,4)}到達点 {r['endpoint']*100:5.1f}%  → {r['x_abs50']:.1f} ms{ci}"
              f"  {r['note']}")
    for fam in FAMS:
        P(f"\n  【視覚 {LAB[fam]}】横軸 進み具合 %")
        for ch in ORDER:
            r = abd[(abd.family_ja == LAB[fam]) & (abd.char == ch)].iloc[0]
            if r["x_abs50"] is None or pd.isna(r["x_abs50"]):
                P(f"  {pad(ch,4)}到達点 {r['endpoint']*100:5.1f}%  → {r['status']}"
                  f"  {r['note']}")
            else:
                ci = (f" [{r['x_abs50_lo']:.2f}, {r['x_abs50_hi']:.2f}]"
                      if r["x_abs50_lo"] is not None and not pd.isna(r["x_abs50_lo"]) else "")
                P(f"  {pad(ch,4)}到達点 {r['endpoint']*100:5.1f}%  → {r['x_abs50']:.2f}%{ci}"
                  f"  {r['note']}")

    P()
    P("=" * 116)
    P("表5. 参考：聴覚を打ち切らずに全部聞かせたとき（曲線の外側の実測。U とは別の量）")
    P("     U は『打ち切りのはしごの終端』（字ごとに 60〜125ms）、こちらは『全長』")
    P("     本課題に埋め込んだ全長提示だけ（出題前の聞き取り確認は含めない）")
    P("=" * 116)
    P("  " + pad("字", 4) + pad("試行", 6) + pad("正答", 6)
      + pad("正答率 [95%区間 Wilson]", 30) + pad("当てずっぽうより上", 20)
      + pad("情報量 [bit]", 14) + pad("最頻の答え", 24))
    for ch in ORDER:
        r = fdf[fdf.char == ch].iloc[0]
        P("  " + pad(ch, 4) + pad(str(r["n_trials"]), 6) + pad(str(r["n_correct"]), 6)
          + pad(f"{r['accuracy']*100:.1f}% [{r['acc_lo_wilson']*100:.1f}, "
                f"{r['acc_hi_wilson']*100:.1f}]", 30)
          + pad("はい" if r["above_chance"] else "いいえ", 20)
          + pad(f"{r['bits_specific_surprise']:.2f}", 14)
          + pad(f"{r['top1']}×{r['top1_n']} / {r['top2']}×{r['top2_n']}"
                f"（答えは{r['n_distinct_responses']}種類）", 24))

    P()
    P("=" * 116)
    P("情報量の指標に使った式（報告に必ず書くこと）")
    P("=" * 116)
    P("  字 c ・ 水準 x での分け前:")
    P("      D_c(x) = KL( P(R|c,x) ‖ P(R|x) ) = Σ_r P(r|c,x)·log2[ P(r|c,x) / P(r|x) ]  [bit]")
    P("  水準 x での相互情報量:")
    P("      I(S;R|x) = Σ_c P(c|x)·D_c(x)          （上限は H(S)=log2(8)=3 bit）")
    P("  R … 参加者が回答盤で選んだ字（聴覚 68 択・視覚 72 択）")
    P("  S … 出した字（本命 8 字）")
    P("  P(R|x) … **その水準の実測の周辺分布**。基準が実測なので、何も届いていないときの")
    P("           回答の偏り（人の事前分布）は自動的に差し引かれ、届いていなければ 0 になる。")
    P("  有限標本の上向きの偏りは、水準の中で字ラベルだけを入れ替える並べ替えの平均を引いて補正。")
    P("  文献での名称: stimulus-specific surprise（specific surprise）。")
    P("    Bezzi (2007) BioSystems 89(1-3):4-9 が I₁ として整理し、Σ_s p(s)·I₁(s)=I(S;R) を明記。")
    P("    ⚠ Butts (2003) の stimulus-specific information (SSI) は別の量なので混同しないこと。")
    P()
    U_hi_over = int((df[df.target == "info"]["U_hi"] > 3.0).sum())
    P(f"  ⚠ 到達点 U の点推定は 40 セルすべて 3 bit 以下（最大 "
      f"{df[df.target == 'info']['U'].max():.2f}）だが、95% 区間の上端は "
      f"{U_hi_over}/40 セルで 3 bit を超える。")
    P("    並べ替えでバイアスを引いた推定量は、理論上限のすぐ下ではばらつきが上限をまたぐ。")
    P("    区間の上端は『3 bit で頭打ち』と読むこと。")

    with open(os.path.join(a.out, "tables.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    keep = ["target", "target_unit", "family_ja", "char", "n_trials", "x_unit",
            "x_min", "x_max", "L", "U", "U_lo", "U_hi", "U_distinguishable_from_L",
            "bottom", "q_at_x_min",
            "T25", "T25_lo", "T25_hi", "T25_status", "T25_frac_censored_boot",
            "T50", "T50_lo", "T50_hi", "T50_status", "T50_frac_censored_boot",
            "T75", "T75_lo", "T75_hi", "T75_status",
            "W", "W_lo", "W_hi", "W_status", "W_frac_ok_boot", "beta_equiv",
            "T50_bracket_lo", "T50_bracket_hi", "reason"]
    df[df.modality == "audio"][keep].to_csv(
        os.path.join(a.out, "three_indices_audio.csv"), index=False)
    df[df.modality == "visual"][keep].to_csv(
        os.path.join(a.out, "three_indices_visual.csv"), index=False)

    print(f"\n出力: {os.path.relpath(a.out, ROOT)}/")
    for fn in sorted(os.listdir(a.out)):
        print(f"  {fn}")


if __name__ == "__main__":
    main()
