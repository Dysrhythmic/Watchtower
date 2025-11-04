from __future__ import annotations
import os
import argparse
import asyncio
import logging
import json
from typing import List, Dict, Optional, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from MessageData import MessageData

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

"""
Error Handling Pattern:

    Use exc_info=True in logger.error() calls for unexpected exceptions that indicate bugs
    or system failures. This includes full tracebacks for debugging.

    Do NOT use exc_info=True for:
    - Expected errors (network timeouts, missing files, config validation)
    - User errors (invalid input, missing credentials)
    - Business logic failures (message routing failures, API rate limits)

    Examples:
        logger.error("Failed to connect", exc_info=True)  # YES - unexpected system error
        logger.error("Invalid config file")                # NO - expected validation error
"""

class Watchtower:
    """Main application coordinating all components."""

    def __init__(self,
                 sources: List[str],
                 config = None,
                 telegram = None,
                 discord = None,
                 router = None,
                 ocr = None,
                 message_queue = None,
                 metrics = None):
        """Initialize Watchtower with dependency injection support.

        Args:
            sources: List of message sources to monitor ("telegram", "rss", "all")
            config: ConfigManager instance (or None to create default)
            telegram: TelegramHandler instance (or None to create default)
            discord: DiscordHandler instance (or None to create default)
            router: MessageRouter instance (or None to create default)
            ocr: OCRHandler instance (or None to create default)
            message_queue: MessageQueue instance (or None to create default)
            metrics: MetricsCollector instance (or None to create default)
        """
        # Lazy imports to avoid loading dependencies unless needed
        from ConfigManager import ConfigManager
        from TelegramHandler import TelegramHandler
        from MessageRouter import MessageRouter
        from DiscordHandler import DiscordHandler
        from OCRHandler import OCRHandler
        from MessageQueue import MessageQueue
        from MetricsCollector import MetricsCollector

        # Use provided instances or create defaults (dependency injection)
        self.config = config or ConfigManager()
        self.telegram = telegram or TelegramHandler(self.config)
        self.router = router or MessageRouter(self.config)
        self.discord = discord or DiscordHandler()
        self.ocr = ocr or OCRHandler()
        self.message_queue = message_queue or MessageQueue()
        self.metrics = metrics or MetricsCollector(self.config.tmp_dir / "metrics.json")

        self.sources = sources
        self.rss = None  # created only if RSS is enabled
        self._shutdown_requested = False
        self._start_time = None  # Track application runtime

        # Clean up any leftover media files from previous runs
        self._cleanup_attachments_dir()

        logger.info("[Watchtower] Initialized")

    def _cleanup_attachments_dir(self):
        """Remove any leftover media files from previous runs."""
        import glob
        attachments_path = self.config.attachments_dir
        if attachments_path.exists():
            files = list(attachments_path.glob('*'))
            if files:
                for file_path in files:
                    try:
                        if file_path.is_file():
                            os.remove(file_path)
                            logger.debug(f"[Watchtower] Cleaned up leftover file: {file_path}")
                    except Exception as e:
                        logger.warning(f"[Watchtower] Failed to clean up {file_path}: {e}")
                logger.info(f"[Watchtower] Cleaned up {len(files)} leftover media files from attachments directory")

    async def start(self) -> None:
        """Start the service."""
        import time
        self._start_time = time.time()
        tasks = []

        # Start message queue processor (background retry task)
        tasks.append(asyncio.create_task(self.message_queue.process_queue(self)))

        # Telegram source
        if 'telegram' in self.sources:
            await self.telegram.start()
            self.telegram.setup_handlers(self._handle_message)
            # connection proofs
            await self.telegram.fetch_latest_messages()
            tasks.append(asyncio.create_task(self.telegram.run()))

        # RSS source
        if 'rss' in self.sources and self.config.rss_feeds:
            from RSSHandler import RSSHandler
            self.rss = RSSHandler(self.config, self._handle_message)
            for feed in self.config.rss_feeds:
                tasks.append(asyncio.create_task(self.rss.run_feed(feed)))

        logger.info(f"[Watchtower] Now monitoring for new messages... (sources={','.join(self.sources)})")

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                logger.info("[Watchtower] Tasks cancelled, shutting down gracefully...")
                await self.shutdown()

    async def shutdown(self):
        """Gracefully shutdown the application."""
        import time
        logger.info("[Watchtower] Initiating graceful shutdown...")
        self._shutdown_requested = True

        # Calculate and save time_ran metric (per-session)
        if self._start_time is not None:
            runtime_seconds = int(time.time() - self._start_time)
            self.metrics.set("time_ran", runtime_seconds)
            logger.info(f"[Watchtower] Application ran for {runtime_seconds} seconds")

        # Log metrics before shutdown
        metrics_summary = self.metrics.get_all()
        if metrics_summary:
            logger.info(f"[Watchtower] Final metrics: {json.dumps(metrics_summary, indent=2)}")

        # Check retry queue status
        queue_size = self.message_queue.get_queue_size()
        if queue_size > 0:
            logger.warning(f"[Watchtower] Shutting down with {queue_size} messages in retry queue (will be lost)")

        # Disconnect Telegram client
        if self.telegram and self.telegram.client.is_connected():
            await self.telegram.client.disconnect()
            logger.info("[Watchtower] Telegram client disconnected")

        logger.info("[Watchtower] Shutdown complete")

    async def _handle_message(self, message_data: 'MessageData', is_latest: bool) -> bool:
        """Process incoming message from any source (Telegram, RSS).

        Returns:
            bool: True if message was successfully routed to at least one destination, False otherwise
        """
        try:
            # Connection proof logging only
            if is_latest:
                logger.info(
                    f"\n[Watchtower] CONNECTION ESTABLISHED\n"
                    f"  Channel: {message_data.channel_name}\n"
                    f"  Latest message by: {message_data.username}\n"
                    f"  Time: {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                )
                return False

            # Track incoming messages by source
            self.metrics.increment(f"messages_received_{message_data.source_type}")

            await self._preprocess_message(message_data)

            destinations = self.router.get_destinations(message_data)
            if not destinations:
                logger.info(f"[Watchtower] Message from {message_data.channel_name} by {message_data.username} has no destinations")
                self.metrics.increment("messages_no_destination")
                return False

            media_passes_restrictions = await self._handle_media_restrictions(message_data, destinations)

            success_count = 0
            for destination in destinations:
                success = await self._dispatch_to_destination(message_data, destination, media_passes_restrictions)
                if success:
                    success_count += 1

            if success_count > 0:
                self.metrics.increment("messages_routed_success")
            else:
                self.metrics.increment("messages_routed_failed")

            return success_count > 0

        except Exception as e:
            logger.error(f"[Watchtower] Error processing message from {message_data.channel_name} by {message_data.username}: {e}", exc_info=True)
            return False

        finally:
            # Clean up media file after all destinations have been processed
            if message_data.media_path and os.path.exists(message_data.media_path):
                try:
                    os.remove(message_data.media_path)
                    logger.debug(f"[Watchtower] Cleaned up media file: {message_data.media_path}")
                except Exception as e:
                    logger.error(f"[Watchtower] Error removing media at {message_data.media_path}: {e}")

    async def _preprocess_message(self, message_data: MessageData):
        """Pre-process message with OCR and defanged URLs.

        OCR allows text extraction from images (e.g., screenshots of checks, invoices)
        for keyword matching and routing.

        Defanged URLs make t.me links non-clickable (hxxps://t[.]me format) to prevent
        accidental navigation to potentially malicious content in CTI workflows.
        """
        ocr_needed = False
        if message_data.source_type == "telegram" and message_data.has_media:
            ocr_needed = self.router.is_ocr_enabled_for_channel(message_data.channel_id, message_data.channel_name)
        if ocr_needed and self.ocr.is_available():
            if not message_data.media_path:
                message_data.media_path = await self.telegram.download_media(message_data)
            if message_data.media_path and os.path.exists(message_data.media_path):
                ocr_text = self.ocr.extract_text(message_data.media_path)
                if ocr_text:
                    message_data.ocr_enabled = True
                    message_data.ocr_raw = ocr_text
                    self.metrics.increment("ocr_processed")

        if message_data.source_type == "telegram" and message_data.original_message:
            telegram_msg_id = getattr(message_data.original_message, "id", None)
            defanged_url = self.telegram.build_defanged_tg_url(
                message_data.channel_id,
                message_data.channel_name,
                telegram_msg_id
            )
            if defanged_url:
                message_data.metadata['src_url_defanged'] = defanged_url

    async def _handle_media_restrictions(self, message_data: MessageData, destinations: List[Dict]) -> bool:
        """Check media restrictions and download media if needed.

        Evaluates whether any destination requires restricted mode filtering,
        checks if the media passes those restrictions, and downloads media
        if at least one destination will accept it.

        Args:
            message_data: The message being processed
            destinations: List of destination configurations

        Returns:
            bool: Whether media passes restriction checks (True if allowed or no restrictions)
        """
        any_destination_has_restricted_mode = any(destination.get('restricted_mode', False) for destination in destinations)

        media_passes_restrictions = True
        if any_destination_has_restricted_mode and message_data.source_type == "telegram" and message_data.has_media and message_data.original_message:
            media_passes_restrictions = self.telegram._is_media_restricted(message_data.original_message)

        if message_data.source_type == "telegram" and message_data.has_media and not message_data.media_path:
            should_download_media = False
            for destination in destinations:
                if destination['type'] in ('discord', 'telegram'):
                    if not destination.get('restricted_mode', False):
                        should_download_media = True
                        break
                    elif media_passes_restrictions:
                        should_download_media = True
                        break
            if should_download_media:
                message_data.media_path = await self.telegram.download_media(message_data)

        return media_passes_restrictions

    async def _dispatch_to_destination(self, message_data: MessageData, destination: Dict, media_passes_restrictions: bool) -> bool:
        """Dispatch message to a single destination (Discord or Telegram).

        Applies destination-specific parsing, formats the message, determines media inclusion,
        and routes to the appropriate sending method based on destination type.

        Args:
            message_data: The message to send
            destination: Destination configuration (contains type, parser, restricted_mode, etc.)
            media_passes_restrictions: Whether media passed restricted mode checks

        Returns:
            bool: True if sent successfully to at least one destination, False otherwise
        """
        parsed_message = self.router.parse_msg(message_data, destination['parser'])

        include_media = False
        if parsed_message.media_path:
            if not destination.get('restricted_mode', False) or media_passes_restrictions:
                include_media = True

        # Use appropriate formatter based on destination type
        if destination['type'] == 'discord':
            content = self.discord.format_message(parsed_message, destination)
            status = await self._send_to_discord(parsed_message, destination, content, include_media)
        elif destination['type'] == 'telegram':
            content = self.telegram.format_message(parsed_message, destination)
            status = await self._send_to_telegram(parsed_message, destination, content, include_media)
        else:
            status = "failed"

        logger.info(f"[Watchtower] Message from {parsed_message.channel_name} by {parsed_message.username} {status} to {destination['name']}")

        # Return True if status indicates success (not "failed")
        return status != "failed"

    async def _send_to_discord(self, parsed_message: MessageData, destination: Dict, content: str, include_media: bool) -> str:
        """Send message to Discord webhook.

        Appends a note if media was blocked by restricted mode, then sends via HTTP POST.

        Args:
            parsed_message: The parsed message with applied parser rules
            destination: Discord webhook destination config
            content: Formatted message text
            include_media: Whether to include media attachment

        Returns:
            str: "sent" if successful, "queued" if enqueued for retry, "failed" otherwise
        """
        if parsed_message.has_media and not include_media:
            if destination.get('restricted_mode', False):
                content += "\n**[Media attachment filtered due to restricted mode]**"
            else:
                content += f"\n**[Media type {parsed_message.media_type} could not be forwarded to Discord]**"

        media_path = parsed_message.media_path if include_media else None
        success = self.discord.send_message(content, destination['webhook_url'], media_path)

        if success:
            self.metrics.increment("messages_sent_discord")
            if parsed_message.ocr_raw:
                self.metrics.increment("ocr_sent")
            return "sent"
        else:
            # Enqueue for retry
            self.message_queue.enqueue(
                destination=destination,
                formatted_content=content,
                media_path=media_path,
                reason="Discord send failed (likely rate limit)"
            )
            self.metrics.increment("messages_queued_retry")
            return "queued for retry"

    async def _send_to_telegram(self, parsed_message: MessageData, destination: Dict, content: str, include_media: bool) -> str:
        """Send message to Telegram channel using copy mode.

        Always uses copy mode (formatted message with optional media) for consistency
        with Discord and to allow parser modifications, keyword display, etc.

        Args:
            parsed_message: The parsed message with applied parser rules
            destination: Telegram destination config with single channel specifier
            content: Formatted message text
            include_media: Whether to include media attachment

        Returns:
            str: Status "sent", "queued for retry", or "failed"
        """
        media_path = self._get_media_for_send(parsed_message, destination, include_media)
        channel_specifier = destination['destination']

        destination_chat_id = await self.telegram.resolve_destination(channel_specifier)
        if destination_chat_id is None:
            logger.warning(f"[TelegramHandler] Skipping unresolved destination: {channel_specifier}")
            return "failed"

        try:
            ok = await self.telegram.send_copy(destination_chat_id, content, media_path)
            if ok:
                self.metrics.increment("messages_sent_telegram")
                if parsed_message.ocr_raw:
                    self.metrics.increment("ocr_sent")
                return "sent"
            else:
                # Send failed, enqueue for retry
                self.message_queue.enqueue(
                    destination=destination,
                    formatted_content=content,
                    media_path=media_path,
                    reason="Telegram send failed (likely rate limit)"
                )
                self.metrics.increment("messages_queued_retry")
                return "queued for retry"
        except Exception as e:
            logger.error(f"[TelegramHandler] Failed to send to {channel_specifier}: {e}")
            return "failed"

    def _get_media_for_send(self, parsed_message: MessageData, destination: Dict, include_media: bool) -> Optional[str]:
        """Determine which media file to send based on restricted mode and OCR settings.

        Args:
            parsed_message: The message being sent
            destination: Destination configuration
            include_media: Whether media should be included at all

        Returns:
            Path to media file or None if media should not be sent
        """
        if not include_media or not parsed_message.media_path:
            return None

        if destination.get('restricted_mode', False):
            if destination.get('ocr', False):
                return None
            return None

        return parsed_message.media_path

def _get_entity_type_and_name(telegram_entity):
    """Extract entity type and name from Telegram entity."""
    from telethon.tl.types import Channel, Chat, User

    entity_type = "Unknown"
    entity_name = "Unknown"

    if isinstance(telegram_entity, Channel):
        if telegram_entity.broadcast:
            entity_type = "Channel"
        elif telegram_entity.megagroup:
            entity_type = "Supergroup"
        else:
            entity_type = "Group"
        entity_name = telegram_entity.title
    elif isinstance(telegram_entity, Chat):
        entity_type = "Group"
        entity_name = telegram_entity.title
    elif isinstance(telegram_entity, User):
        if telegram_entity.bot:
            entity_type = "Bot"
        else:
            entity_type = "User"

        if telegram_entity.username:
            entity_name = f"@{telegram_entity.username}"
        elif telegram_entity.first_name:
            entity_name = telegram_entity.first_name
            if telegram_entity.last_name:
                entity_name += f" {telegram_entity.last_name}"
        else:
            entity_name = f"User{telegram_entity.id}"

    return entity_type, entity_name

def _get_channel_identifier(telegram_entity, dialog_id):
    """Get channel identifier (username or numeric ID)."""
    if hasattr(telegram_entity, 'username') and telegram_entity.username:
        return f"@{telegram_entity.username}"
    return str(dialog_id)

def _load_existing_config(config_dir: Path):
    """Load existing config and return set of channel IDs."""
    config_file_name = os.getenv('CONFIG_FILE', 'config.json')
    config_path = config_dir / config_file_name

    if not config_path.exists():
        logger.info(f"[Discover] No existing config found at {config_path}")
        return set(), {}

    logger.info(f"[Discover] Loading existing config: {config_path}")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            existing_config = json.load(f)

        existing_channel_ids = set()
        existing_channel_details = {}

        destination_list = existing_config.get('destinations', [])

        for destination in destination_list:
            for channel in destination.get('channels', []):
                ch_id = channel.get('id')
                if ch_id and not ch_id.startswith('http'):
                    existing_channel_ids.add(ch_id)
                    existing_channel_details[ch_id] = ch_id

        logger.info(f"[Discover] Found {len(existing_channel_ids)} existing channels in config")
        return existing_channel_ids, existing_channel_details
    except Exception as e:
        logger.error(f"[Discover] Error loading config: {e}")
        return None, None

def _calculate_diff(channels, existing_channel_ids):
    """Calculate new and removed channels."""
    discovered_ids = set(ch['info']['id'] for ch in channels)
    new_channels = [ch for ch in channels if ch['info']['id'] not in existing_channel_ids]
    removed_channel_ids = existing_channel_ids - discovered_ids
    return new_channels, removed_channel_ids

def _print_diff_output(new_channels, removed_channel_ids, existing_channel_ids, all_channels):
    """Print diff mode output."""
    has_changes = len(new_channels) > 0 or len(removed_channel_ids) > 0

    if not has_changes:
        logger.info("")
        logger.info("=" * 70)
        logger.info("✓ NO CHANGES DETECTED")
        logger.info("=" * 70)
        logger.info(f"  All {len(existing_channel_ids)} configured channels are accessible.")
        logger.info(f"  No new channels discovered.")
        logger.info("=" * 70)
        logger.info("")
        return False

    logger.info("")
    logger.info("=" * 70)
    logger.info("CONFIGURATION DIFF")
    logger.info("=" * 70)

    if removed_channel_ids:
        logger.info("")
        logger.info("Removed/Inaccessible (in config but not accessible):")
        for ch_id in sorted(removed_channel_ids):
            logger.info(f"  - {ch_id}")

    if new_channels:
        logger.info("")
        logger.info("New Channels (accessible but not in config):")
        for ch in new_channels:
            logger.info(f"  + {ch['name']:40} [{ch['type']:10}] {ch['info']['id']}")

    type_counts = {}
    for ch in new_channels:
        entity_type = ch.get('type', 'Unknown')
        type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    logger.info(f"  In config: {len(existing_channel_ids):3}  |  Discovered: {len(all_channels):3}  |  New (+): {len(new_channels):3}  |  Removed (-): {len(removed_channel_ids):3}")

    if new_channels:
        type_summary = ", ".join([f"{et}s: {count}" for et, count in sorted(type_counts.items())])
        logger.info(f"  New by type: {type_summary}")

    logger.info("=" * 70)
    logger.info("")
    return True

def _save_discovered_config(channels, config_dir: Path):
    """Save discovered channels to config file.

    Generates a config with the new 'destinations' format.
    To configure Telegram as a destination, change:
    - type: "discord" -> "telegram"
    - env_key: Use an env variable containing the Telegram channel ID (e.g., "@channel" or "-1001234567890")
    """
    config = {
        "destinations": [
            {
                "name": "Auto-Generated Feed",
                "type": "discord",
                "env_key": "DISCORD_WEBHOOK_URL",
                "channels": [ch["info"] for ch in channels]
            }
        ]
    }

    config_path = config_dir / "config_discovered.json"
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    logger.info(f"[Discover] Configuration saved to {config_path}")
    logger.info(f"[Discover] Note: To send to Telegram instead, change type to 'telegram' and set env_key to a Telegram channel ID")

async def discover_channels(diff_mode=False, generate_config=False):
    """Discover all accessible Telegram channels and optionally generate a config file.

    Args:
        diff_mode: If True, show only new channels not in existing config
        generate_config: If True, generate config_discovered.json file
    """
    from telethon import TelegramClient
    from telethon.tl.types import Channel, Chat, User
    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[1]
    config_dir = project_root / "config"
    env_path = config_dir / ".env"
    load_dotenv(dotenv_path=env_path)

    api_id = os.getenv('TELEGRAM_API_ID')
    api_hash = os.getenv('TELEGRAM_API_HASH')

    if not api_id or not api_hash:
        logger.error("[Discover] Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in .env file")
        return

    logger.info("[Discover] Connecting to Telegram...")
    session_path = str(config_dir / "watchtower_session.session")
    client = TelegramClient(session_path, api_id, api_hash)

    await client.start()
    logger.info("[Discover] Connected to Telegram")

    logger.info("[Discover] Fetching all dialogs (channels, groups, bots, users)...")
    dialogs = await client.get_dialogs()

    channels = []
    for dialog in dialogs:
        telegram_entity = dialog.entity

        if isinstance(telegram_entity, User) and telegram_entity.is_self:
            continue

        if isinstance(telegram_entity, (Channel, Chat, User)):
            entity_type, entity_name = _get_entity_type_and_name(telegram_entity)
            channel_id = _get_channel_identifier(telegram_entity, dialog.id)

            channel_info = {
                "id": channel_id,
                "keywords": {"files": [], "inline": []},
                "restricted_mode": False,
                "parser": {"trim_front_lines": 0, "trim_back_lines": 0},
                "ocr": False
            }

            channels.append({
                "name": entity_name,
                "type": entity_type,
                "info": channel_info
            })

            logger.info(f"  Found: {entity_name:40} [{entity_type:10}] ({channel_id})")

    await client.disconnect()

    if not channels:
        logger.warning("[Discover] No dialogs found!")
        return

    if diff_mode:
        existing_channel_ids, existing_channel_details = _load_existing_config(config_dir)
        if existing_channel_ids is None:
            return

        new_channels, removed_channel_ids = _calculate_diff(channels, existing_channel_ids)
        has_changes = _print_diff_output(new_channels, removed_channel_ids, existing_channel_ids, channels)
        if not has_changes:
            return
    else:
        type_counts = {}
        for ch in channels:
            entity_type = ch.get('type', 'Unknown')
            type_counts[entity_type] = type_counts.get(entity_type, 0) + 1

        logger.info(f"\n[Discover] Found {len(channels)} total dialogs:")
        for entity_type, count in sorted(type_counts.items()):
            logger.info(f"  - {entity_type}: {count}")

    # Only generate config file if --generate flag was provided
    if generate_config:
        _save_discovered_config(channels, config_dir)
        logger.info("")
        logger.info("=" * 70)
        logger.info("NEXT STEPS:")
        logger.info("=" * 70)
        logger.info("1. Review the generated config: config/config_discovered.json")
        logger.info("2. Add your Discord webhook URL to .env as DISCORD_WEBHOOK_URL")
        logger.info("3. Optionally add keywords to filter messages per channel")
        logger.info("4. Rename config_discovered.json to config.json (or merge with existing)")
        logger.info("5. Run: python3 src/Watchtower.py monitor --sources telegram")
        logger.info("=" * 70)
    else:
        logger.info("")
        logger.info("To generate a config file from these channels, run:")
        logger.info("  python3 src/Watchtower.py discover --generate")

def main():
    parser = argparse.ArgumentParser(description="Watchtower - CTI Message Routing")
    subparsers = parser.add_subparsers(dest="cmd")

    # monitor subcommand
    monitor_parser = subparsers.add_parser("monitor", help="Run live monitoring/forwarding")
    monitor_parser.add_argument("--sources", default="all", help="Comma-separated: telegram,rss,all (default: all)")

    # discover subcommand
    discover_parser = subparsers.add_parser("discover", help="Auto-generate config from accessible Telegram channels")
    discover_parser.add_argument("--diff", action="store_true", help="Show only new channels not in existing config")
    discover_parser.add_argument("--generate", action="store_true", help="Generate config_discovered.json file")

    args = parser.parse_args()

    if args.cmd == "monitor":
        # Parse sources
        wanted = set(s.strip().lower() for s in args.sources.split(','))
        if "all" in wanted:
            sources = ["telegram", "rss"]
        else:
            sources = [s for s in ("telegram", "rss") if s in wanted]

        app = None
        try:
            app = Watchtower(sources)
            asyncio.run(app.start())
        except KeyboardInterrupt:
            logger.info("[Watchtower] Interrupted by user (Ctrl+C)")
            if app:
                asyncio.run(app.shutdown())
        except Exception as e:
            logger.error(f"[Watchtower] Fatal error: {e}")
            if app:
                asyncio.run(app.shutdown())
            raise

    elif args.cmd == "discover":
        try:
            asyncio.run(discover_channels(diff_mode=args.diff, generate_config=args.generate))
        except KeyboardInterrupt:
            logger.info("[Discover] Cancelled by user")
        except Exception as e:
            logger.error(f"[Discover] Error: {e}", exc_info=True)
            raise

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
