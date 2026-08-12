# BGM Factory

YouTube Shorts／長尺Mix向けのBGMをローカル生成・評価し、動画のPrivate投稿と実績収集を行うWindowsサーバーシステムです。

## 配置

| 用途 | パス |
|---|---|
| コード | `D:\HomeServer\apps\bgm-factory` |
| モデル・DB・生成物 | `D:\HomeServer\data\app-data\bgm-factory` |
| 設定・OAuth秘密情報 | `D:\HomeServer\config\bgm-factory` |
| ログ・PID・heartbeat | `D:\HomeServer\logs\bgm-factory` |

仕様書の `D:\HomeServer\data\files\youtube-bgm` は参照専用です。OAuthクライアントとトークンはリポジトリ外の `config\bgm-factory\secrets` に保存します。

## 起動・停止

HomeServerの通常モードと連動して、ACE-Step API、生成ワーカー、Analyticsダッシュボードを起動・停止します。

```powershell
D:\HomeServer\scripts\start-normal.ps1
D:\HomeServer\scripts\stop-normal.ps1
```

単体操作:

```powershell
D:\HomeServer\apps\bgm-factory\scripts\start.ps1
D:\HomeServer\apps\bgm-factory\scripts\healthcheck.ps1
D:\HomeServer\apps\bgm-factory\scripts\stop.ps1
```

ダッシュボードはサーバー内の `http://127.0.0.1:8787/` で開きます。

## BGM生成

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe enqueue --theme summer_drive --count 1
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe status
```

生成候補は音量、BPM、フック、ループ、品質を解析し、基準を満たしたものだけをAsset化します。毎日03:15に生成し、04:00に一時ファイルを整理します。

## YouTube接続

OAuth認証と接続確認:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe youtube-auth
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe youtube-status
```

レンダリング済み動画を登録し、1本だけPrivate投稿:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe video-register `
  --file D:\path\video.mp4 --kind short --title "BGM Set #1" --tag bgm --tag shorts

D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe youtube-upload-next --confirm-private
```

動画はSHA-256で重複判定します。アップロード結果が不明な場合は `uncertain` で停止し、自動再投稿しません。`auto_upload: true` にすると15分ごとに登録済み動画を1本ずつPrivate投稿します。`auto_publish` は初期状態では無効です。

## Analytics

手動収集:

```powershell
D:\HomeServer\apps\bgm-factory\.venv\Scripts\bgm-factory.exe youtube-collect
```

毎日05:00にYouTube Data APIとYouTube Analytics APIから再生数、高評価、コメント、Engaged views、総再生時間、平均視聴時間、平均視聴率、共有、登録者増加をSQLiteへ保存します。

## 安全設定

- ACE-Step APIとダッシュボードは `127.0.0.1` のみにbindします。
- YouTube投稿先チャンネルIDをサーバー設定に固定し、一致しない認証では投稿しません。
- 初期投稿はPrivate限定です。
- `.env`、OAuth情報、モデル、生成物、DB、ログはGit管理外です。
