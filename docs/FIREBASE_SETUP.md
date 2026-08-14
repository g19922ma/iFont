# Firestore 二重書き込みのセットアップ（乙課題・本番）

GAS には同時実行30本の上限があり、クラウドソーシングの混雑時に書き込みを取りこぼす
恐れがある（送信は no-cors のため失敗をクライアントが検知できない）。そこで
Firestore にも並行保存する（二重書き込み）。**どちらか片方だけでも動く**。
Kikiwake で Firebase 運用実績があるため、同じアカウントで10分で終わる。

## 手順（一度だけ・約10分）

1. **Firebase プロジェクトを作る**（Kikiwake とは別プロジェクト推奨。例: `ifont-exp`）
   https://console.firebase.google.com/ → プロジェクトを追加（Analytics 不要）
2. **Firestore を有効化**: 構築 → Firestore Database → データベースを作成 →
   本番モード・ロケーション asia-northeast1
3. **セキュリティルール**を以下に置き換え（書き込み専用・読み出し不可・更新/削除不可）:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /soa_trials/{doc} {
      allow create: if true;
      allow read, update, delete: if false;
    }
    match /soa_sessions/{doc} {
      allow create: if true;
      allow read, update, delete: if false;
    }
  }
}
```

4. **ウェブAPIキーの取得**: プロジェクトの設定（歯車）→ 全般 → ウェブAPIキー を控える。
   プロジェクトID（例 `ifont-exp`）も控える
5. **experiment/prod_common.js の FIREBASE に記入**:

```js
const FIREBASE = { projectId: "ifont-exp", apiKey: "AIza..." };
```

6. **動作確認**: 乙ページを `?prod=1` で開いて1試行進め、Firestore コンソールの
   `soa_trials` にドキュメントが増えることを確認

## データの取り出し

- 少量なら Firestore コンソールから目視/手動
- まとめては gcloud CLI: `gcloud firestore export gs://<bucket>` または
  Kikiwake の firestore_export と同じ手順。解析側は JSON→CSV 変換1枚（解析時に用意）

## 備考

- APIキーはクライアント公開前提のもの（Firebase の設計上、ルールで守る）。
  ルールが「create のみ」なので、読み出し・改竄・削除はできない
- GAS 側（SUBMIT_URL）も併用可。両方設定すれば二重保存になり、解析時は
  Firestore を正・GAS を照合用とする
