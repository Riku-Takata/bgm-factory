# BGM Factory

YouTube Shorts / 長尺Mix向けのBGM Assetを、Windows 11 + NVIDIA GPU上でローカル生成するシステムです。

現在は、Python環境、ACE-Step 1.5、FFmpeg、SQLiteジョブキュー、GPU ResourceGuard、BGM生成、音響解析、Hook/Loop/Qualityスコア、Asset採否判定、日次スケジューラまで実装しています。YouTubeへの自動投稿は無効です。

## サーバー上の配置

| 用途 | パス |
|---|---|
| コード | `D:\HomeServer\apps\bgm-factory` |
| Python/uv等のツール | `D:\HomeServer\tools` |
| ACE-Step・モデル・DB・生成物 | `D:\HomeServer\data\app-data\bgm-factory` |
| 実行設定・OAuth秘密情報 | `D:\HomeServer\config\bgm-factory` |
| ログ・PID・heartbeat | `D:\HomeServer\logs\bgm-factory` |

仕様書の `D:\HomeServer\data\files\youtube-bgm` は参照専用で、実装や生成物を置きません。

## 初期化

PowerShellで以下を実行します。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
D:\HomeServer\apps\bgm-factory\scripts\install.ps1
```

ACE-Stepの依存関係は大きいため、初回同期には時間と数GBの通信が発生します。モデル本体はACE-Step API初回起動時にダウンロードされます。

## 起動と確認

```powershell
D:\HomeServer\apps\bgm-factory\scripts\start.ps1
D:\HomeServer\apps\bgm-factory\scripts\healthcheck.ps1
D:\HomeServer\apps\bgm-factory\scripts\stop.ps1
```

HomeServer通常モードと連動して起動・停止します。

```powershell
D:\HomeServer\scripts\start-normal.ps1
D:\HomeServer\scripts\stop-normal.ps1
```

Windows Task Schedulerへの登録は不要です。

## ジョブ操作

状態確認:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe status
```

1件をキューへ追加:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe enqueue --theme summer_drive --count 1
```

Workerを使わず次のジョブを1つ処理:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe run-once
```

通常はWorkerがキューを監視します。毎日03:15に40候補のJobを作成し、GPU条件を満たす場合のみ処理します。04:00にRejected Candidateと一時ファイルを整理します。

## 初回に人が行う設定

1. YouTube連携フェーズでGoogle CloudのOAuthクライアントを作り、`secrets\client_secret.json`を配置する。
2. Private投稿の動作確認後にのみ自動アップロードを有効にする。

## 方針

- ACE-Step APIは `127.0.0.1:8001` のみにbindします。
- RTX 3060 Ti 8GB向けに2B turbo + 0.6B LM + PyTorch backend + CPU offloadを初期値とします。
- GPU使用率35%超、モデル未ロード時の空きVRAM 6GB未満、モデルロード済み時の空きVRAM 1.2GB未満、温度78℃超では新しい生成を開始しません。
- Accepted Assetは `data\app-data\bgm-factory\assets` に永久保存します。
- Rejected Candidateは7日後に削除します。
- `.env`、OAuth情報、モデル、生成音源、DB、ログはGit管理外です。
