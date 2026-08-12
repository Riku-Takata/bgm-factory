# BGM Factory

YouTube Shorts / 長尺Mix向けのBGM Assetを、Windows 11 + NVIDIA GPU上でローカル生成するシステムです。

このリポジトリは現在「環境基盤」までを実装しています。Python環境、ACE-Step 1.5、FFmpeg、GPU、保存先、常駐Workerの死活監視を準備し、BGM生成ロジックは次フェーズで追加します。YouTubeへの自動投稿は初期状態で無効です。

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

常時起動タスクの登録は管理者PowerShellで次を実行します。

```powershell
D:\HomeServer\apps\bgm-factory\scripts\register-task.ps1
```

## 初回に人が行う設定

1. ACE-Step APIを一度起動し、モデルのダウンロード完了と生成テストを確認する。
2. YouTube連携フェーズでGoogle CloudのOAuthクライアントを作り、`secrets\client_secret.json`を配置する。
3. Private投稿の動作確認後にのみ自動アップロードを有効にする。

## 方針

- ACE-Step APIは `127.0.0.1:8001` のみにbindします。
- RTX 3060 Ti 8GB向けに2B turbo + 0.6B LM + PyTorch backend + CPU offloadを初期値とします。
- GPU使用率35%超、空きVRAM 6GB未満、温度78℃超では将来の生成Jobを開始しません。
- `.env`、OAuth情報、モデル、生成音源、DB、ログはGit管理外です。
