#!/usr/bin/env python3
"""Social Uploader - CLI entry point (wired in STEP 11)."""
import click
from cli.commands import setup_cmd, upload_cmd, upload_batch_cmd, status_cmd, config_cmd

@click.group()
@click.version_option(version="1.0.0", prog_name="social-uploader")
def cli():
    """Upload edited videos to YouTube, TikTok, and Instagram."""
    pass

cli.add_command(setup_cmd, "setup")
cli.add_command(upload_cmd, "upload")
cli.add_command(upload_batch_cmd, "upload-batch")
cli.add_command(status_cmd, "status")
cli.add_command(config_cmd, "config")

if __name__ == "__main__":
    cli()
