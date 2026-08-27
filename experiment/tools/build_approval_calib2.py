#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calib2バッチ（2026-08-27掲載・163人枠）の品質チェックと承認判定CSVを作る。

■ 入力
  project/data_calib2_live/transfer_trials.csv  … 1問1行の回答記録(is_test除外済み)
  project/data_calib2_live/transfer_roster.csv  … 名簿(誰がどの集団の何番目か)
  project/設問データ_見え方の課題2_0827.tsv     … 配布した設問(cp932, CRLF, タブ区切り)
                                                   1列目が設問ID。本命163行がwid、
                                                   chk01〜chk10はチェック設問なのでwidではない。

■ 出力
  project/data_calib2_live/承認判定_calib2.csv  … 1行1参加者。承認推奨(yes/no)と理由つき。
                                                   Yahoo納品データが来たらwidで結合するだけで
                                                   済むように作ってある(下の「完了コードについて」
                                                   と「Yahoo納品データが来たら」を参照)。

■ 完了コードについて(2026-08-27訂正)
  ⚠ 前バージョンのこのスクリプトは、参加者ごとに異なる completion_code
    (experiment/prod_common.js の codeFromWid()。wid から決まる3桁)を
    「参加者がYahoo側に入力する値」と誤認し、それをYahoo納品データとの
    照合キーにする設計になっていた。これは誤り。

  実際の画面表示は experiment/prod_common.js の completionHTML() 呼び出し
  (transfer.js:2591, 3138)で `hideCode: true, hintTable: true` が指定されており、
    ・hideCode:true  … codeFromWid() の個人別コードは**画面に出さない**
    ・hintTable:true … 代わりに hintTableHTML() が SHARED_CODE="949" を
                        全員に表示する(prod_common.js:307-324、
                        「完了コードの表示（2026-08-27・全員共通に確定）」)
  したがって **参加者がYahoo!の設問で入力する3桁は、実施の有無によらず全員 "949"**
  である。codeFromWid() が作る個人別コードは transfer_trials.csv の
  completion_code 列に記録として残るだけで、参加者自身は一度も目にしない。

  ■ この事実がもたらす結論
    - Yahoo納品データの「回答した3桁」は、正しくやった人はほぼ全員 949 になる
      弱い判定にしかならない。実験をやらずに949を推測(または他人から伝聞)して
      通す不正を防げないため、**これ単独では承認可否を決めない**。
    - **承認可否の実質的な判定は、Firestoreの完走記録(本CSVの「完走したか」
      「品質フラグ」「承認推奨」列)で行う。** これは wid ごとの実データに基づく
      ので、949の推測では突破できない。
    - completion_code(個人別内部コード)は、"内部記録_完了コード整合性"列として
      参考程度に残す(サーバ側の記録パイプラインが正しく動いていたかの自己点検用。
      Yahoo側の値との突き合わせには使わない)。

■ Yahoo納品データが来たら(突き合わせ手順)
  1. Yahoo納品データ(誰が・どの3桁を回答したか)を wid で本CSVに結合する。
  2. Yahoo側の回答が"949"でない/未回答の行を洗い出す → その wid が本CSVで
     「完走したか=True」なら、Yahooの入力ミス・未提出の可能性があるので個別確認。
     「完走したか=False」ならFirestore側とも整合しており、そのまま非承認でよい。
  3. 最終的な承認可否は本CSVの「承認推奨」列(Firestoreの完走記録+品質フラグに
     基づく)を正とする。Yahoo側が949を回答していても、本CSVが「完走したか=False」
     なら承認しない(949は実験をせずに推測できるため)。

■ 品質チェックの考え方
  - full-check(check_kind=="full"、完全可視・打ち切りなし)の正答率は、
    態度確認の最良指標。母集団全体で 98.9%・最小でも 4/6(66.7%) で、
    偶然水準(1/72 ≈ 1.4%)に張り付く参加者はいない。
  - 本命(main)の progress_pct==100 (完全に見える水準)の正答率も同様に高い
    (母集団平均 99.4%、最小 2/3)。
  - 進行度が低い(ほぼ見えない)水準では「あ」「ん」などの決め打ち回答が
    一部の参加者で目立つが、これらの参加者は full-check / p100 の正答率が
    軒並み100%であり、「見えないときは適当な既定文字を出す」という合理的な
    回答戦略であって、でたらめ回答ではないと判断した。dominant_response_share
    単独では除外根拠にしない(full/p100正答率とのAND条件でのみ疑わしいとする)。
  - rt_ms(反応時間)の中央値が極端に短い参加者が1名(mzmggc, 565ms。次点は
    1250msで大きな差がある)おり、かつこの参加者は進行度20%以上の10問中2問
    しか正解していない(母集団平均は同区間で概ね50〜94%)。これは唯一、複数の
    指標が同時に悪化している要注意ケース。
"""

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "project" / "data_calib2_live"
TRIALS_CSV = DATA_DIR / "transfer_trials.csv"
ROSTER_CSV = DATA_DIR / "transfer_roster.csv"
QUESTION_TSV = ROOT / "project" / "設問データ_見え方の課題2_0827.tsv"
OUT_CSV = DATA_DIR / "承認判定_calib2.csv"

PHASE = "calib2"
N_MAIN_EXPECTED = 24  # 本命(transfer_visual, 非decoy/非filler, check_kindなし)の想定問題数

# 全員が完了画面で見る共通ヒント(参加者がYahoo!側の設問に入力する3桁)。
# experiment/prod_common.js の SHARED_CODE と同じ値(transfer.js の呼び出しで
# hideCode:true・hintTable:true が指定されているため、個人別コードではなくこちらが出る)。
SHARED_CODE = "949"


# --- 内部記録用の個人別コード(参加者には非表示・Yahoo照合には使わない)。
#     experiment/prod_common.js の codeFromWid() と同一の式 (FNV-1a → LCG)。
#     transfer_trials.csv の completion_code 列に記録として残る値の再現に使う
#     (サーバ側の記録パイプラインの自己点検用)。
def code_from_wid(wid: str) -> str:
    h = 0x811C9DC5
    src = "ifont-cc-2026|" + str(wid)
    for ch in src:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    out = []
    for _ in range(3):
        h = (h * 1664525 + 1013904223) & 0xFFFFFFFF
        out.append(str(h % 10))
    return "".join(out)


def load_question_wids() -> list[str]:
    """配布用TSVから本命wid(chk01〜chk10を除く)を順序保持で返す。"""
    df = pd.read_csv(QUESTION_TSV, sep="\t", encoding="cp932", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    idcol = df.columns[0]
    wid_rows = df[~df[idcol].str.startswith("chk")]
    return wid_rows[idcol].tolist()


def main() -> None:
    trials = pd.read_csv(TRIALS_CSV, low_memory=False)
    roster = pd.read_csv(ROSTER_CSV)
    tsv_wids = load_question_wids()

    d2 = trials[trials["phase"] == PHASE].copy()
    r2 = roster[roster["phase"] == PHASE].copy()

    # --- タスク1-1: is_testの混入チェック ---
    n_is_test_full = int((trials["is_test"] == True).sum())  # noqa: E712  (ファイル全体)
    n_is_test_calib2 = int((d2["is_test"] == True).sum())  # noqa: E712

    d2["correct_b"] = d2["correct"].astype(str).str.upper() == "TRUE"

    main = d2[
        (d2["modality"] == "transfer_visual")
        & (d2["is_decoy"] != True)  # noqa: E712
        & (d2["is_filler"] != True)  # noqa: E712
        & (d2["check_kind"].isna())
    ].copy()
    full_check = d2[d2["check_kind"] == "full"].copy()

    all_wids = sorted(set(tsv_wids) | set(r2["participant_id"]) | set(d2["participant_id"]))

    rows = []
    for wid in all_wids:
        distributed = wid in tsv_wids
        rostered = wid in set(r2["participant_id"])
        d2_p = d2[d2["participant_id"] == wid]
        main_p = main[main["participant_id"] == wid]
        full_p = full_check[full_check["participant_id"] == wid]

        started = len(d2_p) > 0
        n_total_rows = int(len(d2_p))
        n_main = int(len(main_p))
        completed = n_main >= N_MAIN_EXPECTED  # ← 承認可否の実質的な根拠(Firestore側の完走記録)

        p100 = main_p[main_p["progress_pct"] == 100]
        acc_p100 = round(float(p100["correct_b"].mean()), 4) if len(p100) else None
        n_p100 = int(len(p100))

        acc_full = round(float(full_p["correct_b"].mean()), 4) if len(full_p) else None
        n_full = int(len(full_p))

        rt_median_main = float(main_p["rt_ms"].median()) if n_main else None

        if n_main:
            resp_counts = main_p["response_char"].value_counts()
            dominant_share = round(float(resp_counts.iloc[0] / n_main), 4)
            dominant_char = resp_counts.index[0]
        else:
            dominant_share = None
            dominant_char = None

        # 高進行度(>=20%、本命のみ)での正答率。低進行度の「あ」既定回答戦略と
        # 区別するための補助指標。
        hi = main_p[main_p["progress_pct"] >= 20]
        acc_hi = round(float(hi["correct_b"].mean()), 4) if len(hi) else None
        n_hi = int(len(hi))

        # 内部記録の個人別コード(参考列。Yahoo照合には使わない)。
        completion_code_logged = None
        post = d2_p[d2_p["modality"] == "transfer_post_survey"]
        if len(post) and post["completion_code"].notna().any():
            completion_code_logged = str(post["completion_code"].dropna().iloc[0]).zfill(3)
        completion_code_wid_calc = code_from_wid(wid)
        internal_code_consistent = (
            completion_code_logged == completion_code_wid_calc
            if completion_code_logged is not None
            else None
        )

        # --- 品質フラグ ---
        flags = []
        if not distributed:
            flags.append("配布リストに無いwid(要確認)")
        if distributed and not started:
            flags.append("未実施(一度も開いていない)")
        elif started and not completed:
            flags.append(f"未完走(本命{n_main}/{N_MAIN_EXPECTED}問)")
        if n_full and acc_full is not None and acc_full <= 0.5:
            flags.append(f"full-check正答率が低い({acc_full:.0%}, {n_full}問)")
        if n_p100 and acc_p100 is not None and acc_p100 <= 0.5:
            flags.append(f"100%可視水準の正答率が低い({acc_p100:.0%}, {n_p100}問)")
        if rt_median_main is not None and rt_median_main < 800:
            flags.append(f"反応時間の中央値が極端に短い({rt_median_main:.0f}ms)")
        if (
            dominant_share is not None
            and dominant_share > 0.5
            and (
                (acc_full is not None and acc_full < 1.0)
                or (acc_p100 is not None and acc_p100 < 1.0)
            )
        ):
            flags.append(
                f"同一文字への偏り(最頻回答'{dominant_char}'が{dominant_share:.0%})"
                "かつ高可視水準でも誤答あり"
            )
        if (
            n_hi >= 5
            and acc_hi is not None
            and acc_hi < 0.3
            and rt_median_main is not None
            and rt_median_main < 1200
        ):
            flags.append(
                f"進行度20%以上でも正答率が低い({acc_hi:.0%}, {n_hi}問)"
                "かつ反応が速い(でたらめ回答の疑い)"
            )
        if completion_code_logged is not None and internal_code_consistent is False:
            flags.append("内部記録の完了コードがwid計算値と不一致(データパイプライン要調査)")

        quality_flag = "; ".join(flags) if flags else ""

        # --- 承認推奨(Firestoreの完走記録+品質フラグのみで判定。949は使わない) ---
        if not distributed:
            approve = "no"
            reason = "配布リスト外のwid。掲載データと突き合わせて要確認。"
        elif not started:
            approve = "no"
            reason = "未実施(課題を一度も開いていない)。"
        elif not completed:
            approve = "no"
            reason = f"未完走(本命{n_main}/{N_MAIN_EXPECTED}問で離脱)。"
        elif (
            n_hi >= 5
            and acc_hi is not None
            and acc_hi < 0.3
            and rt_median_main is not None
            and rt_median_main < 1200
        ):
            approve = "no"
            reason = (
                f"完走はしているが、進行度20%以上(見えやすい水準)でも正答率{acc_hi:.0%}"
                f"({n_hi}問中)と低く、反応時間の中央値も{rt_median_main:.0f}msと速い。"
                "でたらめ/不注意な回答の疑いが強いため非推奨。要人手確認。"
            )
        elif n_full and acc_full is not None and acc_full <= 0.5:
            approve = "no"
            reason = f"確認問題(full)の正答率が{acc_full:.0%}({n_full}問中)と低い。"
        else:
            approve = "yes"
            reason = "本命24問完走(Firestore記録)。full-check/100%可視水準ともに高正答率で、でたらめ回答の兆候なし。"
            if quality_flag:
                reason += f" ただし要確認事項あり: {quality_flag}"

        rows.append(
            {
                "wid": wid,
                "配布済みか": distributed,
                "名簿登録済みか": rostered,
                "開始したか": started,
                "本命回答数": n_main,
                "総行数": n_total_rows,
                "完走したか(Firestore記録・承認判定の主根拠)": completed,
                "100%水準_正答数": n_p100,
                "100%水準_正答率": acc_p100,
                "full確認問題_正答数": n_full,
                "full確認問題_正答率": acc_full,
                "進行度20%以上_正答率": acc_hi,
                "進行度20%以上_問題数": n_hi,
                "反応時間中央値_ms": round(rt_median_main, 1) if rt_median_main is not None else None,
                "最頻回答文字": dominant_char,
                "最頻回答文字の割合": dominant_share,
                "Yahoo設問の想定回答(全員共通・弱い判定)": SHARED_CODE if distributed else None,
                "内部記録_完了コード(参考・Yahoo照合には使わない)": completion_code_logged,
                "内部記録_完了コードwid計算値(参考)": completion_code_wid_calc if started else None,
                "内部記録整合性(自己点検用)": internal_code_consistent,
                "品質フラグ": quality_flag,
                "承認推奨": approve,
                "理由": reason,
            }
        )

    out = pd.DataFrame(rows)
    out = out.sort_values(["承認推奨", "wid"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)

    # --- サマリ表示 ---
    n_total = len(out)
    n_yes = int((out["承認推奨"] == "yes").sum())
    n_no = int((out["承認推奨"] == "no").sum())
    n_flagged_yes = int(((out["承認推奨"] == "yes") & (out["品質フラグ"] != "")).sum())

    print(f"[is_test混入] 全体: {n_is_test_full}件 / calib2内: {n_is_test_calib2}件")
    print(f"[対象wid数] {n_total} (配布{len(tsv_wids)} / 名簿{len(set(r2['participant_id']))} / trials内{d2['participant_id'].nunique()})")
    print(
        "[完了コード] Yahoo!側で参加者が入力するのは全員共通 "
        f"\"{SHARED_CODE}\"(prod_common.js の SHARED_CODE。hideCode:true+hintTable:true で"
        "個人別コードは非表示)。承認可否はこれを使わず、Firestoreの完走記録(本命"
        f"{N_MAIN_EXPECTED}問到達)で判定した。"
    )
    print(f"[承認推奨] yes={n_yes} (うち品質フラグ付き={n_flagged_yes}) / no={n_no}")
    print()
    print("[no の内訳理由]")
    print(out[out["承認推奨"] == "no"]["理由"].value_counts().to_string())
    print()
    print("[yes だが品質フラグありの明細]")
    print(
        out[(out["承認推奨"] == "yes") & (out["品質フラグ"] != "")][
            ["wid", "本命回答数", "100%水準_正答率", "full確認問題_正答率", "反応時間中央値_ms", "品質フラグ"]
        ].to_string(index=False)
    )
    print()
    print(f"[出力] {OUT_CSV}")


if __name__ == "__main__":
    sys.exit(main())
