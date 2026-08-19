#!/usr/bin/env python3
# A1.5: 実験全体(群A測定→推定→生成→freeze→群B測定→判定)を通したシミュレーション
# A1への批判5点を反映:
#  1) 参加者ごとの閾値差(SD10ms)と傾き差(対数正規SD0.2)
#  2) 文字ごとの転写誤差τを主たるランダム効果として扱う(現実的な帰無=τ>0)
#  3) lapseは文字ごとに変え(1〜8%)、推定でもlapseを自由パラメータにする(Wichmann-Hill)
#  4) 群Aの推定誤差を生成に通す: 視覚の真の曲線 = 群Aの「推定」中点 + シナリオのずれ
#     判定は μ̂B − μ̂A (ターゲット=推定値との比較。方法の主張に対応)
#  5) 時点配置のミスマッチ: 急峻な曲線(中点55ms・s=8ms)に等間隔20..200msを当てる設計も評価
import numpy as np
rng = np.random.default_rng(20260820)

GAMMA = 0.015
MU_GRID = np.arange(20, 172, 2.0)          # 76
S_GRID  = np.arange(6, 42, 2.0)            # 18
L_GRID  = np.array([0.0, 0.02, 0.04, 0.06, 0.08])   # lapse自由推定
GM, GS, GL = np.meshgrid(MU_GRID, S_GRID, L_GRID, indexing="ij")
GRID_SHAPE = GM.shape

def fit(counts, N, t):
    """文字ごとグリッド最尤(μ,s,λ)。counts:(reps,K,T) → μ̂,ŝ:(reps,K)"""
    P = GAMMA + (1 - GAMMA - GL[..., None]) / (1 + np.exp(-(t - GM[..., None]) / GS[..., None]))
    P = np.clip(P, 1e-6, 1 - 1e-6)                          # (Gm,Gs,Gl,T)
    logP, log1P = np.log(P), np.log(1 - P)
    Gflat = logP.reshape(-1, len(t))                        # (G,T)
    G1flat = log1P.reshape(-1, len(t))
    ll = counts @ Gflat.T + (N - counts) @ G1flat.T         # (reps,K,G)
    idx = ll.argmax(axis=2)
    mi, si, li = np.unravel_index(idx, GRID_SHAPE)
    return MU_GRID[mi], S_GRID[si], L_GRID[li]

def sample_responses(N, t, mu_char, s_char, lapse_char, reps, K):
    """参加者の閾値差(SD10ms)・傾き差(logN SD0.2)込みで回答を生成。"""
    dmu_p = rng.normal(0, 10, size=(reps, 1, 1, N))
    fs_p  = np.exp(rng.normal(0, 0.2, size=(reps, 1, 1, N)))
    logit = (t[None, None, :, None] - (mu_char[:, :, None, None] + dmu_p)) / (s_char[:, :, None, None] * fs_p)
    p = GAMMA + (1 - GAMMA - lapse_char[:, :, None, None]) / (1 + np.exp(-logit))
    return (rng.random(p.shape) < p).sum(axis=3).astype(np.float64)

def run(N, T, K, mu_pop, s_pop, scenarios, reps=300, t_override=None):
    t = t_override if t_override is not None else np.linspace(20, 200, T)
    # 真の音声曲線(文字ごと): 中点SD15ms・傾き±20%・lapse1〜8%
    muA = np.clip(rng.normal(mu_pop, 15, size=(reps, K)), 30, 160)
    sA  = s_pop * np.exp(rng.normal(0, 0.2, size=(reps, K)))
    lam = rng.uniform(0.01, 0.08, size=(reps, K))
    cA = sample_responses(N, t, muA, sA, lam, reps, K)
    muA_hat, sA_hat, lA_hat = fit(cA, N, t)                  # ← このターゲットで生成する
    out = []
    for (name, dmu, tau, rho) in scenarios:
        # 視覚の真の曲線 = 群Aの推定値 + 系統ずれΔ + 文字ごとの転写誤差τ、傾きはρ倍
        muV = muA_hat + dmu + (rng.normal(0, tau, size=muA_hat.shape) if tau else 0.0)
        sV  = sA_hat / rho
        cB = sample_responses(N, t, muV, sV, lam, reps, K)   # lapseは同じ文字特性を仮定
        muB_hat, sB_hat, lB_hat = fit(cB, N, t)
        D = (muB_hat - muA_hat).mean(axis=1)
        R = np.exp(np.log(sA_hat / sB_hat).mean(axis=1))
        SDD = (muB_hat - muA_hat).std(axis=1)                # 文字ごとの差のばらつき(τの回復)
        # 曲線距離E: あてはめ曲線どうしの、時点上の平均絶対差(確率ポイント)
        def curves(mu, sc, la):
            return GAMMA + (1 - GAMMA - la[:, :, None]) / (1 + np.exp(-(t[None, None, :] - mu[:, :, None]) / sc[:, :, None]))
        PA = curves(muA_hat, sA_hat, lA_hat)
        PV = curves(muB_hat, sB_hat, lB_hat)
        E = np.abs(PA - PV).mean(axis=(1, 2)) * 100          # (reps,) 単位: ポイント
        out.append((name, D.mean(), D.std(), R.mean(), R.std(), SDD.mean(), E.mean(), E.std()))
    return out

def report(title, rows):
    print(f"### {title}")
    print("| シナリオ | 中点差の推定 (平均±SD) | 傾き比 (平均±SD) | 文字間差SDの推定 | 曲線距離E(pt) |")
    print("|---|---|---|---|---|")
    for (name, dm, ds, rm, rs, sdd, em, es) in rows:
        print(f"| {name} | {dm:+.1f}±{ds:.1f} ms | {rm:.2f}±{rs:.2f} | {sdd:.1f} ms | {em:.1f}±{es:.1f} |")
    print()

def main():
    scenarios = [
        ("完全転写(Δ0,τ0)",        0, 0, 1.0),
        ("現実的成功(τ=10ms)",     0, 10, 1.0),
        ("転写ムラ大(τ=15ms)",     0, 15, 1.0),
        ("系統ずれΔ=20(τ=10)",    20, 10, 1.0),
        ("傾き劣化ρ=0.6(τ=10)",    0, 10, 0.6),
    ]
    for (N, T, K, label) in [(25, 7, 8, "標準候補 N25/T7/K8"),
                              (25, 5, 8, "軽量 N25/T5/K8"),
                              (40, 7, 10, "手厚い N40/T7/K10")]:
        rows = run(N, T, K, mu_pop=90, s_pop=18, scenarios=scenarios)
        report(f"{label}(曲線: 中点90ms・s18ms・時点20-200ms等間隔)", rows)
    # 時点ミスマッチ: 急峻(中点55ms, s=8ms)に等間隔を当てる vs 低域寄せ配置
    rows = run(25, 7, 8, mu_pop=55, s_pop=8, scenarios=scenarios)
    report("ミスマッチ: 急峻曲線(中点55ms,s8ms)×等間隔20-200ms (N25/T7/K8)", rows)
    t_low = np.array([20, 35, 50, 65, 80, 110, 200.0])
    rows = run(25, 7, 8, mu_pop=55, s_pop=8, scenarios=scenarios, t_override=t_low)
    report("同じ急峻曲線×低域寄せ配置[20,35,50,65,80,110,200] (N25/T7/K8)", rows)

if __name__ == "__main__":
    main()
