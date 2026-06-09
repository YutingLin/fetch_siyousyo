"""
CLI entry point for the Japanese government procurement scraper.

Usage
-----
python main.py scrape \\
    --keyword "システム開発" --keyword "DX" \\
    --date-from 2023-01-01 \\
    --date-to   2024-12-31 \\
    --output-dir ./downloads \\
    --source digital_agency \\
    --dry-run

python main.py scrape \\
    --source generic \\
    --base-url "https://www.soumu.go.jp/menu_sinsei/s-tokosei/bid.html" \\
    --agency-name "総務省" \\
    --output-dir ./downloads
"""

import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime

import click
from tqdm import tqdm

# Ensure the project root is on sys.path so that ``import config`` works
sys.path.insert(0, os.path.dirname(__file__))

from config import DEFAULT_OUTPUT_DIR, RESULTS_FILE, SOURCES
from src.downloader import download_pdf
from src.pairer import pair_documents, summarise_pairs
from src.scrapers.base import ProcurementRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_scraper(source: str, base_url: str, agency_name: str):
    """Instantiate the appropriate scraper based on *source*."""
    if source == "digital_agency":
        from src.scrapers.digital_agency import DigitalAgencyScraper
        return DigitalAgencyScraper()

    if source == "soumu":
        from src.scrapers.generic import GenericScraper
        cfg = SOURCES.get("soumu", {})
        return GenericScraper(
            base_url=base_url or cfg.get("base_url", ""),
            agency_name=agency_name or cfg.get("name", "総務省"),
            source_name="soumu",
        )

    if source == "generic":
        from src.scrapers.generic import GenericScraper
        if not base_url:
            raise click.UsageError(
                "--base-url is required when --source is 'generic'."
            )
        return GenericScraper(
            base_url=base_url,
            agency_name=agency_name or base_url,
            source_name="generic",
        )

    raise click.UsageError(
        f"Unknown source '{source}'. Choose from: digital_agency, soumu, generic."
    )


def _print_summary_table(paired_records) -> None:
    """Print a human-readable summary table to stdout."""
    summary = summarise_pairs(paired_records)
    click.echo("\n" + "=" * 70)
    click.echo("  調達書類スクレイピング結果サマリー")
    click.echo("=" * 70)
    click.echo(f"  対象レコード数           : {summary['total_records']}")
    click.echo(f"  完全ペア (仕様書+提案書) : {summary['complete_pairs']}")
    click.echo(f"  仕様書のみ               : {summary['shiyousho_only']}")
    click.echo(f"  仕様書ファイル総数       : {summary['total_shiyousho_docs']}")
    click.echo(f"  提案書ファイル総数       : {summary['total_teian_docs']}")
    click.echo("=" * 70 + "\n")

    if not paired_records:
        click.echo("  該当するレコードが見つかりませんでした。")
        return

    header = f"{'#':>3}  {'タイトル':<40}  {'日付':^10}  {'仕':^4}  {'提':^4}  ペア"
    click.echo(header)
    click.echo("-" * 70)
    for i, pr in enumerate(paired_records, 1):
        title = pr.record.title[:38] + ".." if len(pr.record.title) > 40 else pr.record.title
        date = pr.record.date or "----/--/--"
        pair_mark = "✓" if pr.is_complete_pair else "-"
        click.echo(
            f"{i:>3}  {title:<40}  {date:^10}  "
            f"{len(pr.shiyousho):^4}  {len(pr.teian):^4}  {pair_mark}"
        )
    click.echo("")


def _save_results(
    paired_records,
    output_dir: str,
    source: str,
    keywords,
    date_from: str,
    date_to: str,
    download_metadata: list,
) -> str:
    """Save results.json to output_dir and return the file path."""
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, RESULTS_FILE)

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "query": {
            "source": source,
            "keywords": list(keywords),
            "date_from": date_from,
            "date_to": date_to,
        },
        "summary": summarise_pairs(paired_records),
        "records": [pr.to_dict() for pr in paired_records],
        "downloads": download_metadata,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return results_path


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------


@click.group()
def cli():
    """調達書類スクレイパー — 仕様書・提案書 PDF を自動収集するツール。"""


@cli.command("scrape")
@click.option(
    "--keyword", "-k",
    "keywords",
    multiple=True,
    help="分野キーワード (複数指定可)。例: --keyword システム開発 --keyword DX",
)
@click.option(
    "--date-from",
    default="",
    show_default=True,
    help="検索開始日 YYYY-MM-DD。省略時は制限なし。",
)
@click.option(
    "--date-to",
    default="",
    show_default=True,
    help="検索終了日 YYYY-MM-DD。省略時は制限なし。",
)
@click.option(
    "--output-dir", "-o",
    default=DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="ダウンロード先ルートディレクトリ。",
)
@click.option(
    "--source", "-s",
    default="digital_agency",
    show_default=True,
    type=click.Choice(["digital_agency", "soumu", "generic"], case_sensitive=False),
    help="スクレイピング対象ソース。",
)
@click.option(
    "--base-url",
    default="",
    help="--source generic 時の対象 URL。",
)
@click.option(
    "--agency-name",
    default="",
    help="エージェント名 (generic ソース時に表示用)。",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="一覧表示のみ。PDF のダウンロードを行わない。",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="デバッグログを表示する。",
)
def scrape_cmd(
    keywords,
    date_from,
    date_to,
    output_dir,
    source,
    base_url,
    agency_name,
    dry_run,
    verbose,
):
    """
    調達ページをスクレイピングして仕様書・提案書 PDF を収集・ダウンロードします。
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    click.echo(f"ソース      : {source}")
    click.echo(f"キーワード  : {', '.join(keywords) if keywords else '(なし — 全件)'}")
    click.echo(f"期間        : {date_from or '(無制限)'} 〜 {date_to or '(無制限)'}")
    click.echo(f"出力先      : {output_dir}")
    click.echo(f"ドライラン  : {'はい' if dry_run else 'いいえ'}\n")

    # Build scraper
    try:
        scraper = _load_scraper(source, base_url, agency_name)
    except click.UsageError as exc:
        click.echo(f"エラー: {exc}", err=True)
        sys.exit(1)

    # Search
    click.echo("スクレイピング中...")
    try:
        records = scraper.search(
            keywords=list(keywords),
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as exc:
        logger.error("スクレイピング中にエラーが発生しました: %s", exc, exc_info=True)
        click.echo(f"エラー: {exc}", err=True)
        sys.exit(1)

    if not records:
        click.echo("該当するレコードが見つかりませんでした。")
        sys.exit(0)

    click.echo(f"{len(records)} 件のレコードが見つかりました。ペアリング処理中...\n")

    # Pair documents
    paired = pair_documents(records)

    # Display summary table
    _print_summary_table(paired)

    if dry_run:
        click.echo("--dry-run 指定のため、ダウンロードをスキップします。")
        results_path = _save_results(
            paired, output_dir, source, keywords, date_from, date_to, []
        )
        click.echo(f"結果を保存しました: {results_path}")
        return

    # Download PDFs
    download_metadata = []
    all_docs = [
        (pr, doc)
        for pr in paired
        for doc in (pr.shiyousho + pr.teian)
    ]

    click.echo(f"{len(all_docs)} 件の PDF をダウンロードします...\n")
    with tqdm(total=len(all_docs), unit="file", desc="ダウンロード") as pbar:
        for pr, doc in all_docs:
            meta = download_pdf(
                url=doc.url,
                source=scraper.source_name,
                project_id=pr.record.id,
                doc_type=doc.doc_type,
                output_dir=output_dir,
                referer=pr.record.url,
            )
            meta["record_id"] = pr.record.id
            meta["record_title"] = pr.record.title
            meta["doc_type"] = doc.doc_type
            download_metadata.append(meta)
            status = "OK" if meta["success"] else f"FAIL: {meta.get('error', '')}"
            pbar.set_postfix_str(status)
            pbar.update(1)

    success_count = sum(1 for m in download_metadata if m["success"])
    click.echo(
        f"\nダウンロード完了: {success_count}/{len(all_docs)} 件成功"
    )

    # Save results JSON
    results_path = _save_results(
        paired, output_dir, source, keywords, date_from, date_to, download_metadata
    )
    click.echo(f"結果を保存しました: {results_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
