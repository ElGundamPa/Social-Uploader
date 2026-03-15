# CLI commands - full implementation
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from core.config_manager import ConfigManager
from core.video_processor import VideoProcessor
from core.queue_manager import QueueManager
from core.logging_config import setup_logging
from core.exceptions import SocialUploaderError, AuthenticationError, QuotaExceededError
from core.uploader_factory import get_uploader as _get_uploader
from uploaders.base import VideoMetadata, UploadResult
from cli.setup_wizard import run_setup_wizard, AVAILABLE_PLATFORMS
from core.uploader_factory import get_uploader_from_credentials as _get_uploader_for_validation

console = Console()


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


@click.command("setup")
@click.option("--profile", default="default", help="Named profile to create.")
def setup_cmd(profile: str) -> None:
    """Interactive credentials setup."""
    setup_logging()
    run_setup_wizard(profile=profile)


@click.command("upload")
@click.argument("video_path", type=click.Path(exists=True))
@click.option("--title", required=True, help="Video title.")
@click.option("--description", default="", help="Video description.")
@click.option("--tags", default="", help="Comma-separated tags.")
@click.option("--platforms", default="", help="Comma-separated: youtube,tiktok,instagram (default: all enabled).")
@click.option("--schedule", default=None, help='Schedule datetime: "2024-12-25 10:00".')
@click.option("--thumbnail", type=click.Path(exists=True), default=None, help="Custom thumbnail image path.")
@click.option("--private", is_flag=True, help="Upload as private/draft.")
@click.option("--profile", default="default", help="Use named profile.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose console logging.")
def upload_cmd(
    video_path: str,
    title: str,
    description: str,
    tags: str,
    platforms: str,
    schedule: str | None,
    thumbnail: str | None,
    private: bool,
    profile: str,
    verbose: bool,
) -> None:
    """Upload a video to selected platforms."""
    setup_logging(verbose=verbose)
    video_path = str(Path(video_path).resolve())
    processor = VideoProcessor()
    validation = processor.validate(video_path)
    if not validation.is_valid:
        console.print("[red]Validation failed:[/red]", validation.errors)
        raise SystemExit(1)

    manager = ConfigManager(profile=profile)
    platform_list = [p.strip().lower() for p in platforms.split(",") if p.strip()] if platforms else manager.list_platforms()
    if not platform_list:
        console.print("[yellow]No platforms enabled. Run: social-uploader setup[/yellow]")
        raise SystemExit(1)

    for p in platform_list:
        errs = processor.check_platform_limits(validation, p)
        if errs:
            console.print(f"[red]{p}:[/red] " + "; ".join(errs))
            raise SystemExit(1)

    thumbnail_path = thumbnail
    if not thumbnail_path:
        try:
            thumbnail_path = processor.extract_thumbnail(video_path, at_second=1.0)
        except Exception as e:
            console.print(f"[yellow]Thumbnail extraction skipped: {e}[/yellow]")

    info = processor.get_video_info(video_path)
    duration_m = int(info["duration_seconds"] // 60)
    duration_s = int(info["duration_seconds"] % 60)
    duration_str = f"{duration_m}:{duration_s:02d}"

    console.print(Panel("[bold]Social Uploader[/bold]  •  Uploading 1 video", title="🎬"))
    console.print(f"  File:       [cyan]{Path(video_path).name}[/cyan] ({validation.file_size_mb:.0f} MB)")
    console.print(f"  Duration:   [cyan]{duration_str}[/cyan]  •  {info['resolution']}  •  {info['codec']}")
    console.print(f'  Title:      [cyan]"{title}"[/cyan]')
    console.print(f"  Platforms:  [cyan]{'  •  '.join(p.capitalize() for p in platform_list)}[/cyan]")
    console.print("  Validating...        [green]✓[/green] All checks passed")
    console.print("  Thumbnail...         [green]✓[/green] Extracted at 00:01" if thumbnail_path else "  Thumbnail...         (none)")

    metadata = VideoMetadata(
        title=title,
        description=description,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
        thumbnail_path=thumbnail_path,
        is_private=private,
        schedule_at=schedule,
    )

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )
    tasks_id = {p: progress.add_task(f" {p.capitalize()}", total=100) for p in platform_list}
    results_by_platform = {}
    max_workers = min(3, len(platform_list))

    def run_one(platform: str):
        uploader = _get_uploader(profile, platform)
        return platform, uploader.upload(video_path, metadata)

    with progress:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_one, p): p for p in platform_list}
            for fut in as_completed(futures):
                platform = futures[fut]
                progress.update(tasks_id[platform], completed=50)
                try:
                    _, res = fut.result()
                    results_by_platform[platform] = res
                except Exception as e:
                    results_by_platform[platform] = UploadResult(platform=platform.capitalize(), success=False, error=str(e))
                progress.update(tasks_id[platform], completed=100)

    normalized = [results_by_platform[p] for p in platform_list]

    table = Table(title="Upload Complete")
    table.add_column("Platform", style="cyan")
    table.add_column("Result", style="green")
    for r in normalized:
        cell = r.url or r.error or "—"
        status = "✓" if r.success else "✗"
        table.add_row(r.platform, f"{status}  {cell}")
    console.print(Panel(table, title="✅  Upload Complete"))

    manager.save_upload_record({
        "video_path": video_path,
        "title": title,
        "platforms": platform_list,
        "results": [{"platform": r.platform, "success": r.success, "url": r.url, "error": r.error} for r in normalized],
    })
    logging.getLogger(__name__).info("Upload finished: %s -> %s", video_path, [r.model_dump() for r in normalized])


@click.command("upload-batch")
@click.argument("folder_path", type=click.Path(exists=True, file_okay=False))
@click.option("--profile", default="default")
def upload_batch_cmd(folder_path: str, profile: str) -> None:
    """Batch upload from folder (recursive .mp4, .mov, .avi, .mkv + optional .json metadata)."""
    setup_logging()
    folder = Path(folder_path)
    extensions = {".mp4", ".mov", ".avi", ".mkv"}
    video_files = []
    for ext in extensions:
        video_files.extend(folder.rglob(f"*{ext}"))
    video_files = sorted(set(video_files))

    if not video_files:
        console.print("[yellow]No video files found.[/yellow]")
        raise SystemExit(0)

    manager = ConfigManager(profile=profile)
    platform_list = manager.list_platforms()
    if not platform_list:
        console.print("[yellow]No platforms enabled. Run: social-uploader setup[/yellow]")
        raise SystemExit(1)

    processor = VideoProcessor()
    queue = QueueManager(_root())
    queue.set_uploader_factory(_get_uploader)
    all_results = []

    for i, vpath in enumerate(video_files):
        console.print(f"[{i+1}/{len(video_files)}] [cyan]{vpath.name}[/cyan]")
        json_path = vpath.with_name(vpath.stem + ".json")  # my_video.mp4 -> my_video.json
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                title = data.get("title", vpath.stem)
                description = data.get("description", "")
                tags = data.get("tags", [])
                platforms = data.get("platforms", platform_list)
                if isinstance(tags, list):
                    tags = tags
                else:
                    tags = [str(t) for t in (tags or "").split(",") if t]
            except Exception as e:
                console.print(f"  [yellow]JSON error: {e}, using defaults[/yellow]")
                title = vpath.stem
                description = ""
                tags = []
                platforms = platform_list
        else:
            title = vpath.stem
            description = ""
            tags = []
            platforms = platform_list

        validation = processor.validate(str(vpath))
        if not validation.is_valid:
            all_results.append({"file": str(vpath), "error": "Validation failed: " + "; ".join(validation.errors)})
            continue
        metadata = VideoMetadata(title=title, description=description, tags=tags)
        try:
            results = queue.process_queue(str(vpath), metadata, platforms, profile)
            all_results.append({"file": str(vpath), "title": title, "results": [r.model_dump() for r in results]})
        except Exception as e:
            all_results.append({"file": str(vpath), "error": str(e)})

    out_path = folder / "upload_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    console.print(f"[green]Results saved to {out_path}[/green]")


@click.command("status")
@click.option("--profile", default="default")
def status_cmd(profile: str) -> None:
    """Show platform status and last 20 upload history entries."""
    setup_logging()
    manager = ConfigManager(profile=profile)
    table = Table(title="Platform status")
    table.add_column("Platform", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Auth", style="yellow")
    table.add_column("Last upload", style="dim")

    for name in AVAILABLE_PLATFORMS:
        enabled = manager.is_platform_enabled(name)
        auth = "—"
        if enabled:
            try:
                creds = manager.load_credentials(name)
                if name == "youtube":
                    # Only check token file exists — don't trigger OAuth browser flow
                    token_path = creds.get("token_path", "")
                    resolved = (manager._root / token_path) if token_path and not os.path.isabs(token_path) else Path(token_path) if token_path else None
                    auth = "[green]Token found[/green]" if (resolved and resolved.exists()) else "[yellow]No token (run setup)[/yellow]"
                else:
                    up = _get_uploader_for_validation(name, creds)
                    up.validate_credentials()
                    auth = "[green]OK[/green]"
            except Exception as e:
                auth = f"[red]Fail[/red] ({e})"
        table.add_row(name.capitalize(), "Yes" if enabled else "No", auth, "—")

    console.print(table)
    history = manager.get_upload_history(limit=20)
    if history:
        htable = Table(title="Last 20 uploads")
        htable.add_column("Timestamp", style="dim")
        htable.add_column("Title", style="cyan")
        htable.add_column("Platforms", style="green")
        htable.add_column("Result", style="yellow")
        for h in history:
            ts = h.get("timestamp", "—")[:19].replace("T", " ") if h.get("timestamp") else "—"
            title = h.get("title", "—")
            platforms = ", ".join(h.get("platforms", []))
            results = h.get("results", [])
            result_str = "  ".join(
                f"{'✓' if r.get('success') else '✗'} {r.get('platform','')}"
                for r in results
            )
            htable.add_row(ts, title, platforms, result_str or "—")
        console.print(htable)


@click.command("config")
@click.option("--platform", required=True, help="Platform to reconfigure (youtube, tiktok, instagram).")
@click.option("--profile", default="default")
def config_cmd(platform: str, profile: str) -> None:
    """Re-run credential collection for a specific platform."""
    setup_logging()
    platform = platform.lower()
    if platform not in AVAILABLE_PLATFORMS:
        console.print(f"[red]Unknown platform: {platform}[/red]")
        raise SystemExit(1)
    from cli.setup_wizard import _collect_youtube, _collect_tiktok, _collect_instagram
    root = _root()
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    manager = ConfigManager(profile=profile)
    if platform == "youtube":
        creds = _collect_youtube(config_dir)
    elif platform == "tiktok":
        creds = _collect_tiktok()
    else:
        creds = _collect_instagram(config_dir)
    try:
        uploader = _get_uploader_for_validation(platform, creds)
        uploader.validate_credentials()
        manager.save_credentials(platform, creds)
        console.print(f"[green]✓[/green] {platform} validated and saved.")
    except Exception as e:
        console.print(f"[red]✗[/red] {e}")
        if click.confirm("Save credentials anyway?"):
            manager.save_credentials(platform, creds)
            console.print("Saved.")
