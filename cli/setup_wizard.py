"""Interactive credentials setup wizard using rich."""
import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from core.config_manager import ConfigManager
from core.uploader_factory import get_uploader_from_credentials as _get_uploader_for_validation

console = Console()

AVAILABLE_PLATFORMS = ["youtube", "tiktok", "instagram"]


def _collect_youtube(config_dir: Path) -> dict:
    path = Prompt.ask(
        "Path to YouTube client secret JSON",
        default=str(config_dir / "youtube_client_secret.json"),
    )
    token_path = str(config_dir / "youtube_token.json")
    return {
        "enabled": True,
        "client_secret_path": path,
        "token_path": token_path,
    }


def _collect_tiktok() -> dict:
    client_key = Prompt.ask("TikTok client key")
    client_secret = Prompt.ask("TikTok client secret", password=True)
    access_token = Prompt.ask("TikTok user access token (from OAuth flow)")
    username = Prompt.ask("TikTok username (without @, used to build video URLs)")
    return {
        "enabled": True,
        "client_key": client_key,
        "client_secret": client_secret,
        "access_token": access_token,
        "username": username,
    }


def _collect_instagram(config_dir: Path) -> dict:
    username = Prompt.ask("Instagram username")
    password = Prompt.ask("Instagram password", password=True)
    session_path = str(config_dir / "instagram_session.json")
    return {
        "enabled": True,
        "username": username,
        "password": password,
        "session_path": session_path,
    }


def run_setup_wizard(profile: str = "default") -> None:
    """Run interactive setup: select platforms, collect credentials, validate, save."""
    root = Path(__file__).resolve().parent.parent
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel("[bold]Social Uploader – Credentials Setup[/bold]", title="Setup"))
    console.print(f"Profile: [cyan]{profile}[/cyan]\n")

    # Multi-select platforms
    to_setup = []
    for name in AVAILABLE_PLATFORMS:
        if Confirm.ask(f"Enable [cyan]{name}[/cyan]?", default=False):
            to_setup.append(name)

    if not to_setup:
        console.print("[yellow]No platforms selected. Exiting.[/yellow]")
        return

    manager = ConfigManager(profile=profile)
    results = []

    for platform in to_setup:
        console.print(Panel(f"Configuring [cyan]{platform}[/cyan]", title=platform.capitalize()))
        if platform == "youtube":
            creds = _collect_youtube(config_dir)
        elif platform == "tiktok":
            creds = _collect_tiktok()
        elif platform == "instagram":
            creds = _collect_instagram(config_dir)
        else:
            continue

        # Validate
        try:
            uploader = _get_uploader_for_validation(platform, creds)
            uploader.validate_credentials()
            manager.save_credentials(platform, creds)
            results.append((platform, True, None))
            console.print(f"  [green]✓[/green] {platform} validated and saved.")
        except Exception as e:
            results.append((platform, False, str(e)))
            console.print(f"  [red]✗[/red] {platform} validation failed: [red]{e}[/red]")
            if Confirm.ask("Save credentials anyway?", default=False):
                manager.save_credentials(platform, creds)
                console.print("  Saved (validation failed).")

    # Summary
    console.print()
    console.print(Panel("Setup summary", title="Summary"))
    for platform, ok, err in results:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        msg = "OK" if ok else (err or "Failed")
        console.print(f"  {status} {platform}: {msg}")
    console.print(f"\nCredentials saved to [cyan]{manager._credentials_path}[/cyan]")
