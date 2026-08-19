#!/usr/bin/env python3
# A1: 設計感度シミュレーション（最終Nの確定ではない）
# 目的: どの規模(参加者数N×時点数T×文字数K)なら「音声→視覚の転写の成否」を区別できそうかを掴む。
# 前提: 心理測定曲線ベース(生の時点差は使わない)。群A(音声)と群B(視覚)は独立参加者。
#       文字ごとに曲線を推定して集約(階層モデルの簡易近似)。lapse・文字間ばらつき・参加者差を入れる。
# 出力: 各設計について、真に等価なときの推定誤差(精度)と、中点シフト・傾き劣化シナリオでの推定値。
import numpy as np

rng = np.random.default_rng(20260819)

GAMMA = 0.015          # 当て推量の床(≈1/68)
LAPSE = 0.03           # 手すべり率(真値)
FIT_LAPSE = 0.03       # 推定時に仮定するlapse(既知扱い・A1の簡易化)
MU_POP = 90.0          # 中点の母平均(ms)
SLOPE_MS = 18.0        # 傾きスケール(ms)。小さいほど急峻
P_SD = 0.5             # 参加者ランダム切片(logit)

MU_GRID = np.arange(30, 172, 2.0)      # 71
S_GRID = np.arange(8, 42, 2.0)         # 17
GG_MU, GG_S = np.meshgrid(MU_GRID, S_GRID, indexing="ij")  # (71,17)

def timepoints(T):
    # 10%〜100%(200ms)を等間隔にT点
    return np.linspace(20, 200, T)

def true_p(t, mu, s):
    return GAMMA + (1 - GAMMA - LAPSE) / (1 + np.exp(-(t - mu) / s))

def simulate_counts(N, T, mus, slope_ratio, reps):
    """各文字×時点の正答数を生成。mus:(reps,K)は呼び出し側で用意(両群で同じ文字=対応づけ設計)。"""
    t = timepoints(T)                                    # (T,)
    s = SLOPE_MS / slope_ratio                           # ratio<1 → 視覚が緩やか
    base = (t[None, None, :] - mus[:, :, None]) / s      # (reps,K,T)
    pe = rng.normal(0, P_SD, size=(reps, 1, 1, N))       # 参加者ランダム切片(logit)
    logit = base[:, :, :, None] + pe                     # (reps,K,T,N)
    p = GAMMA + (1 - GAMMA - LAPSE) / (1 + np.exp(-logit))
    counts = (rng.random(p.shape) < p).sum(axis=3)       # (reps,K,T)
    return counts.astype(np.float64)

def fit_grid(counts, N, T):
    """文字ごとにグリッドMLE。counts:(reps,K,T) → mu_hat,s_hat:(reps,K)"""
    t = timepoints(T)
    P = GAMMA + (1 - GAMMA - FIT_LAPSE) / (1 + np.exp(-(t[None, None, :] - GG_MU[:, :, None]) / GG_S[:, :, None]))
    P = np.clip(P, 1e-6, 1 - 1e-6)                       # (71,17,T)
    logP, log1P = np.log(P), np.log(1 - P)
    reps, K, _ = counts.shape
    ll = np.einsum("rkt,mst->rkms", counts, logP) + np.einsum("rkt,mst->rkms", N - counts, log1P)
    flat = ll.reshape(reps, K, -1).argmax(axis=2)
    mi, si = np.unravel_index(flat, GG_MU.shape)
    return MU_GRID[mi], S_GRID[si]

def run(N, T, K, sigma_char, scenarios, reps=300):
    rows = []
    # 同じK文字を両群で使う(対応づけ)。文字の真の中点は共有。
    mus0 = np.clip(rng.normal(MU_POP, sigma_char, size=(reps, K)), 45, 155)
    cA = simulate_counts(N, T, mus0, 1.0, reps)
    muA, sA = fit_grid(cA, N, T)
    for (dmu, rho, tau) in scenarios:
        musB = mus0 + dmu + (rng.normal(0, tau, size=mus0.shape) if tau else 0.0)
        cB = simulate_counts(N, T, musB, rho, reps)
        muB, sB = fit_grid(cB, N, T)
        D = (muB - muA).mean(axis=1)                     # (reps,) 全体の中点差の推定
        R = np.exp(np.log(sA / sB).mean(axis=1))         # 傾き比(音声s/視覚s: 1=同じ,>1=視覚が急峻)
        rows.append(dict(dmu=dmu, rho=rho,
                         D_mean=D.mean(), D_sd=D.std(),
                         R_mean=R.mean(), R_sd=R.std()))
    return rows

def main():
    # (中点シフトΔ, 傾き比ρ, 文字ごとの転写ムラτ)
    scenarios = [(0, 1.0, 0), (10, 1.0, 0), (20, 1.0, 0), (30, 1.0, 0), (0, 0.6, 0), (0, 1.0, 15)]
    print("| N/群 | 時点 | 文字 | 字ばらつき | 精度σ_D(ms) | Δ=20の推定 | Δ=30の推定 | 傾き0.6時の比 | 転写ムラτ=15時のσ_D |")
    print("|---|---|---|---|---|---|---|---|")
    results = []
    for K in (6, 10):
        for sigma_char in (15, 30):
            for T in (5, 7, 9):
                for N in (15, 25, 40, 60):
                    rows = run(N, T, K, sigma_char, scenarios)
                    null = rows[0]; d20 = rows[2]; d30 = rows[3]; sl = rows[4]; het = rows[5]
                    results.append((N, T, K, sigma_char, null, d20, d30, sl))
                    print(f"| {N} | {T} | {K} | {sigma_char}ms | {null['D_sd']:.1f} "
                          f"| {d20['D_mean']:.0f}±{d20['D_sd']:.0f} "
                          f"| {d30['D_mean']:.0f}±{d30['D_sd']:.0f} "
                          f"| {sl['R_mean']:.2f}±{sl['R_sd']:.2f} "
                          f"| {het['D_sd']:.1f} |")
    # 判別可能性の目安: Δ=20msのシフトが精度の3倍以上なら「区別できそう」
    print()
    print("候補(σ_D≤5ms かつ 1人あたり K×T ≤ 60問/モダリティ):")
    for (N, T, K, sc, null, d20, d30, sl) in results:
        trials = K * T
        if null["D_sd"] <= 5 and trials <= 60:
            print(f"  N={N}/群, 時点{T}, 文字{K}, 字SD{sc}ms → σ_D={null['D_sd']:.1f}ms, 1人あたり{trials}問/モダリティ")

if __name__ == "__main__":
    main()
