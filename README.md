# fetch_siyousyo
ウェブから公共調達の仕様書・提案書 PDF を自動収集するツール。

## インストール

```bash
pip install -r requirements.txt
```

## 使い方

```bash
python main.py scrape [OPTIONS]
```

### 主なオプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--keyword`, `-k` | 分野キーワード（複数指定可） | なし（全件） |
| `--date-from` | 検索開始日 `YYYY-MM-DD` | 無制限 |
| `--date-to` | 検索終了日 `YYYY-MM-DD` | 無制限 |
| `--source`, `-s` | スクレイピング対象ソース | `digital_agency` |
| `--output-dir`, `-o` | ダウンロード先ディレクトリ | `./downloads` |
| `--max-downloads` | ダウンロードする PDF の最大件数（0=無制限） | `0` |
| `--dry-run` | 一覧表示のみ、ダウンロードしない | `false` |
| `--base-url` | `generic` ソース使用時の対象 URL | — |
| `--agency-name` | `generic` ソース使用時の機関名 | — |
| `--verbose`, `-v` | デバッグログを表示 | `false` |

## 対応ソース (`--source`)

| ソース名 | 機関 | URL |
|---|---|---|
| `digital_agency` | デジタル庁 | https://www.digital.go.jp/procurement/ |
| `soumu` | 総務省 | https://www.soumu.go.jp/menu_sinsei/s-tokosei/bid.html |
| `generic` | 任意の省庁・自治体 | `--base-url` で指定 |

## 使用例

```bash
# デジタル庁から「システム開発」案件を検索してダウンロード
python main.py scrape \
  --keyword "システム開発" --keyword "DX" \
  --date-from 2023-01-01 \
  --date-to 2024-12-31 \
  --source digital_agency \
  --output-dir ./downloads

# 総務省からダウンロード（最大20件）
python main.py scrape \
  --source soumu \
  --max-downloads 20 \
  --output-dir ./downloads

# 任意の自治体ページを対象に（ダウンロードせず一覧確認）
python main.py scrape \
  --source generic \
  --base-url "https://www.city.example.lg.jp/procurement/" \
  --agency-name "○○市" \
  --dry-run
```

## 出力

- `downloads/<ソース名>/<案件ID>/仕様書_<ファイル名>.pdf`
- `downloads/<ソース名>/<案件ID>/提案書_<ファイル名>.pdf`
- `downloads/results.json` — 全案件のメタデータとペア情報

## 収集対象

| 種別 | 判定キーワード例 |
|---|---|
| 仕様書 | 仕様書、業務仕様、要件定義、調達仕様、RFP |
| 提案書 | 提案書、技術提案、採択提案、採用提案 |
| 対象外（スキップ） | 入札公告、落札結果、審査結果、議事録、契約書 |
