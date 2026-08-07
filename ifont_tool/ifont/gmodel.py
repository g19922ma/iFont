"""文字単位の視聴覚対応(変換 g)の仮モデル。

本モックアップでは、論文の想定結果版で用いた擬似的な g（聴覚の閾値と視覚の閾値の
おおむね単調な関係）を、文字ごとの「視覚の見せ方のスケジュール」に落とし込む。
実データが得られたら per-character の閾値テーブルに差し替える想定の、プレースホルダである。

g の役割:
  各文字が、その文字の音が流れる区間の中で、どこまで露出すれば読めるようになるか
  (視覚の閾値 thr, 0..1) を返す。thr が小さい文字ほど早く鮮明になり、大きい文字ほど
  区間の終盤までかけて鮮明になる。
"""
import hashlib

# 論文の想定 g（視覚閾値 ≒ 0.85×聴覚閾値 + 8[%], 相関 r≈0.86）に沿った範囲。
_THR_LOW, _THR_HIGH = 0.35, 0.75


def _stable_unit(ch: str) -> float:
    """文字から決定論的に [0,1) の値を作る（実行ごとに変わらないように）。"""
    h = hashlib.sha1(ch.encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big") / 2**32


def visual_threshold(ch: str) -> float:
    """文字 ch の視覚の閾値 thr（その文字の区間のうち、鮮明化にかける割合）。"""
    return _THR_LOW + (_THR_HIGH - _THR_LOW) * _stable_unit(ch)


# 鮮明化のしかた。"mock" は上の擬似 g（文字ごとに閾値が違う）、
# "linear" は文字によらず区間いっぱいを使って一次関数で鮮明化する仮の g。
# 実データが無い段階で「速さと同期」だけを見せたいときは linear を使う。
_MODE = "mock"


def set_mode(mode: str) -> None:
    """鮮明化のしかたを選ぶ。"mock"(既定) か "linear"。"""
    global _MODE
    if mode not in ("mock", "linear"):
        raise ValueError(f"g のモードが不正: {mode}（mock か linear）")
    _MODE = mode


def reveal_opacity(ch: str, local_t: float) -> float:
    """文字 ch の、区間内での相対時刻 local_t(0..1) における不透明度(0..1)。

    mock:   文字ごとの閾値 thr までで 0→1 に立ち上がり、以降は 1 を保つ（smoothstep）。
    linear: 文字によらず、区間の始まりから終わりまで一次関数で 0→1 に立ち上がる。
    """
    x = max(0.0, min(1.0, local_t))
    if _MODE == "linear":
        return x
    thr = max(visual_threshold(ch), 1e-3)
    x = max(0.0, min(1.0, local_t / thr))
    # smoothstep でなめらかに
    return x * x * (3 - 2 * x)
