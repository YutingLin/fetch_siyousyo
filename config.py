"""
Default settings and source configurations for the procurement scraper.
"""

import os

# HTTP request settings
REQUEST_TIMEOUT = 30  # seconds
REQUEST_DELAY = 1.5   # seconds between requests
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0

USER_AGENT = (
    "Mozilla/5.0 (compatible; ProcurementScraper/1.0; "
    "+https://github.com/example/procurement-scraper)"
)

# Default output directory
DEFAULT_OUTPUT_DIR = "./downloads"

# Source configurations
SOURCES = {
    "digital_agency": {
        "name": "デジタル庁",
        "base_url": "https://www.digital.go.jp/procurement/",
        "encoding": "utf-8",
        "css_selectors": {
            "listing": "a[href]",
            "pagination": "a.next, a[rel='next'], .pagination a",
        },
    },
    "soumu": {
        "name": "総務省",
        "base_url": "https://www.soumu.go.jp/menu_sinsei/s-tokosei/bid.html",
        "encoding": "utf-8",
        "css_selectors": {
            "listing": "a[href]",
            "pagination": "a.next, .pager a",
        },
    },
}

# Document classification keywords
SHIYOUSHO_KEYWORDS = [
    "仕様書",
    "仕様",
    "業務仕様",
    "要件定義",
    "調達仕様",
    "業務要件",
    "技術仕様",
    "システム仕様",
    "RFP",
    "提案依頼書",
    # 入札公告はスコープ（仕様）を含む調達文書
    "入札公告",
    # 業務の内容を示す表現（自治体調達でよく使われる）
    "業務一式",
    "業務委託",
    "委託業務",
    "賃借業務",
    "リース業務",
]

TEIANSHŌ_KEYWORDS = [
    "提案書",
    "提案資料",
    "採択",
    "採用提案",
    "技術提案",
    "提案内容",
    "採択提案",
]

# スキップ対象は「結果・通知・議事録」など調達仕様と無関係な文書のみ
# 「公告」「結果」は広すぎるため除外（仕様書・提案書キーワードが優先）
SKIP_KEYWORDS = [
    "落札結果",
    "審査結果",
    "選定結果",
    "入札結果",
    "評価結果",
    "落札",
    "議事録",
    "契約書",
    "価格調書",
    "内訳書",
]

# Encoding detection order for Japanese government sites
ENCODING_CANDIDATES = ["utf-8", "shift_jis", "euc-jp", "iso-2022-jp", "cp932"]

# Results file name
RESULTS_FILE = "results.json"
