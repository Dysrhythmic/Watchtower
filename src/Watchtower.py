"""
Watchtower - Main orchestrator for message monitoring and routing

This module contains the core Watchtower application that coordinates all components
to monitor message sources (Telegram, RSS) and route matching messages to configured
destinations (Discord, Telegram) based on keywords and filters.

Architecture:
    Watchtower serves as the central coordinator that:
    1. Initializes all handlers (Telegram, Discord, RSS, OCR)
    2. Starts message monitoring on configured sources
    3. Routes messages through MessageRouter based on keywords
    4. Applies per-destination transformations (parsing, formatting)
    5. Handles media downloads and restrictions
    6. Manages retry queue for failed deliveries
    7. Collects metrics and handles graceful shutdown

Message Flow:
    1. Source (Telegram/RSS) receives message → converts to MessageData
    2. Watchtower._handle_message() receives MessageData
    3. Pre-process: OCR extraction, URL defanging
    4. MessageRouter finds matching destinations based on keywords
    5. For each destination:
        a. Apply parser (trim lines if configured)
        b. Format message (Discord markdown or Telegram HTML)
        c. Check media restrictions
        d. Send via DiscordHandler or TelegramHandler
        e. On failure: enqueue for retry via MessageQueue
    6. Clean up: Remove downloaded media files

Key Components:
    - ConfigManager: Loads config.json and environment variables
    - TelegramHandler: Source + destination for Telegram
    - RSSHandler: Source for RSS feeds
    - DiscordHandler: Destination for Discord webhooks
    - MessageRouter: Keyword matching and routing logic
    - OCRHandler: Text extraction from images
    - MessageQueue: Retry queue with exponential backoff
    - MetricsCollector: Usage statistics tracking

Error Handling Pattern:
    Use exc_info=True in __logger.error() calls for unexpected exceptions that indicate bugs
    or system failures (includes full tracebacks for debugging).

    Do NOT use exc_info=True for:
    - Expected errors (network timeouts, missing files, config validation)
    - User errors (invalid input, missing credentials)
    - Business logic failures (message routing failures, API rate limits)

    Examples:
        __logger.error("Failed to connect", exc_info=True)  # YES - unexpected system error
        __logger.error("Invalid config file")                # NO - expected validation error

Subcommands:
    monitor: Run live message monitoring and routing
        --sources: Comma-separated sources (telegram, rss, or all)

    discover: Auto-generate config from accessible Telegram channels
        --diff: Show only new channels not in existing config
        --generate: Write config_discovered.json file
"""
from __future__ import annotations
import os
import argparse
import asyncio
import glob
import json
import time
from typing import List, Dict, Optional, TYPE_CHECKING
from pathlib import Path
from LoggerSetup import setup_logger
from Discover import discover_channels
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD, APP_TYPE_RSS

if TYPE_CHECKING:
    from MessageData import MessageData

_logger = setup_logger(__name__)

class Watchtower:
    """Main application orchestrator for CTI message routing.

    Coordinates all components to monitor message sources (Telegram, RSS feeds)
    and intelligently route matching messages to configured destinations (Discord,
    Telegram) based on keyword filtering and per-destination configuration.

    Attributes:
        config: ConfigManager instance with application configuration
        telegram: TelegramHandler for Telegram operations (source + destination)
        discord: DiscordHandler for Discord webhook delivery
        router: MessageRouter for keyword matching and routing
        ocr: OCRHandler for text extraction from images
        message_queue: MessageQueue for retry handling
        metrics: MetricsCollector for usage statistics
        sources: List of enabled sources ("telegram", "rss")
        rss: RSSHandler instance (created if RSS is enabled)
    """

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

        _logger.info("[Watchtower] Initialized")

    def _cleanup_attachments_dir(self):
        """Remove any leftover media files from previous runs.

        Cleans the tmp/attachments directory of any files remaining from
        previous application runs (e.g., if app crashed before cleanup).
        Runs during initialization to ensure clean state.
        """
        attachments_path = self.config.attachments_dir
        if attachments_path.exists():
            files = list(attachments_path.glob('*'))
            if files:
                for file_path in files:
                    try:
                        if file_path.is_file():
                            os.remove(file_path)
                            _logger.debug(f"[Watchtower] Cleaned up leftover file: {file_path}")
                    except Exception as e:
                        _logger.warning(f"[Watchtower] Failed to clean up {file_path}: {e}")
                _logger.info(f"[Watchtower] Cleaned up {len(files)} leftover media files from attachments directory")

    async def start(self) -> None:
        """Start the Watchtower service.

        Initializes all configured sources (Telegram, RSS) and their handlers,
        starts the message queue processor for retries, and keeps the service running.

        Returns:
            None
        """
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
            # Start polling for missed messages
            tasks.append(asyncio.create_task(self.telegram.poll_missed_messages(self.metrics)))

        # RSS source
        if 'rss' in self.sources and self.config.rss_feeds:
            from RSSHandler import RSSHandler
            self.rss = RSSHandler(self.config, self._handle_message)
            for feed in self.config.rss_feeds:
                tasks.append(asyncio.create_task(self.rss.run_feed(feed)))

        _logger.info(f"[Watchtower] Now monitoring for new messages... (sources={','.join(self.sources)})")

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                _logger.info("[Watchtower] Tasks cancelled, returning to main...")

    async def shutdown(self):
        """Gracefully shutdown the application.

        Stops all sources (Telegram, RSS), disconnects clients, saves metrics.

        Returns:
            None
        """
        _logger.info("[Watchtower] Initiating graceful shutdown...")
        self._shutdown_requested = True

        # Calculate and save seconds_ran metric
        if self._start_time is not None:
            runtime_seconds = int(time.time() - self._start_time)
            self.metrics.set("seconds_ran", runtime_seconds)

        # Force save metrics before shutdown (in case periodic save hasn't triggered)
        self.metrics.force_save()

        # Log metrics before shutdown with explanatory note
        # NOTE: All metrics are PER-SESSION (reset on each startup)
        metrics_summary = self.metrics.get_all()
        if metrics_summary:
            _logger.info(
                f"[Watchtower] Final metrics for this session:\n"
                f"{json.dumps(metrics_summary, indent=2)}"
            )

        # Check retry queue status
        queue_size = self.message_queue.get_queue_size()
        if queue_size > 0:
            _logger.warning(f"[Watchtower] Shutting down with {queue_size} messages in retry queue (will be lost)")

        # Clear telegram logs (don't process messages sent during downtime)
        if self.telegram:
            self._clear_telegram_logs()

        # Disconnect Telegram client
        if self.telegram and self.telegram.client.is_connected():
            await self.telegram.client.disconnect()
            _logger.info("[Watchtower] Telegram client disconnected")

        _logger.info("[Watchtower] Shutdown complete")

    def _clear_telegram_logs(self):
        """Clear all telegram log files on shutdown.

        Removes all .txt files in the telegramlog directory. Telegram logs are
        not persistent across restarts since we don't want to process messages
        sent during downtime.

        Called during shutdown to prevent stale log files from affecting next startup.

        Returns:
            None

        Note:
            Errors during cleanup are logged but non-fatal (shutdown continues)
        """
        try:
            telegramlog_dir = self.config.telegramlog_dir
            if telegramlog_dir.exists():
                count = 0
                for log_file in telegramlog_dir.glob("*.txt"):
                    log_file.unlink()
                    count += 1
                _logger.info(f"[Watchtower] Cleared {count} telegram log file(s)")
        except Exception as e:
            _logger.error(f"[Watchtower] Error clearing telegram logs: {e}")

    async def _handle_message(self, message_data: 'MessageData', is_latest: bool) -> bool:
        """Process incoming message from any source (Telegram, RSS).

        Central message processing pipeline that:
        1. Handles connection proof logging (is_latest=True messages)
        2. Pre-processes message (OCR, URL defanging)
        3. Routes to matching destinations via MessageRouter
        4. Checks media restrictions for each destination
        5. Dispatches message to each destination
        6. Tracks metrics and handles errors
        7. Cleans up media files in finally block

        Args:
            message_data: Incoming message from Telegram or RSS source
            is_latest: If True, this is a connection proof message (not routed)

        Returns:
            bool: True if message was successfully routed to at least one destination,
                  False if no destinations matched or all deliveries failed
        """
        try:
            # Connection proof logging only
            if is_latest:
                _logger.info(
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
                _logger.info(f"[Watchtower] Message from {message_data.channel_name} by {message_data.username} has no destinations")
                self.metrics.increment("total_msgs_no_destination")
                return False

            media_passes_restrictions = await self._handle_media_restrictions(message_data, destinations)

            success_count = 0
            for destination in destinations:
                success = await self._dispatch_to_destination(message_data, destination, media_passes_restrictions)
                if success:
                    success_count += 1

            if success_count > 0:
                self.metrics.increment("total_msgs_routed_success")
            else:
                self.metrics.increment("total_msgs_routed_failed")

            return success_count > 0

        except Exception as e:
            _logger.error(f"[Watchtower] Error processing message from {message_data.channel_name} by {message_data.username}: {e}", exc_info=True)
            return False

        finally:
            # Clean up media file after all destinations have been processed
            if message_data.media_path and os.path.exists(message_data.media_path):
                try:
                    os.remove(message_data.media_path)
                    _logger.debug(f"[Watchtower] Cleaned up media file: {message_data.media_path}")
                except Exception as e:
                    _logger.error(f"[Watchtower] Error removing media at {message_data.media_path}: {e}")

    async def _preprocess_message(self, message_data: MessageData):
        """Pre-process message with OCR and defanged URLs.

        OCR allows text extraction from images (e.g., screenshots of checks, invoices)
        for keyword matching and routing.

        Defanged URLs make t.me links non-clickable (hxxps://t[.]me format) to prevent
        accidental navigation to potentially malicious content in CTI workflows.
        """
        ocr_needed = False
        if message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_media:
            ocr_needed = self.router.is_ocr_enabled_for_channel(message_data.channel_id, message_data.channel_name, message_data.source_type)
        if ocr_needed and self.ocr.is_available():
            if not message_data.media_path:
                message_data.media_path = await self.telegram.download_media(message_data)
            if message_data.media_path and os.path.exists(message_data.media_path):
                # Only attempt OCR on image files
                if self._is_image_file(message_data.media_path):
                    ocr_text = self.ocr.extract_text(message_data.media_path)
                    if ocr_text:
                        message_data.ocr_enabled = True
                        message_data.ocr_raw = ocr_text
                        self.metrics.increment("ocr_processed")
                else:
                    _logger.debug(f"[Watchtower] Skipping OCR for non-image file: {message_data.media_path}")

        if message_data.source_type == APP_TYPE_TELEGRAM and message_data.original_message:
            telegram_msg_id = getattr(message_data.original_message, "id", None)
            defanged_url = self.telegram.build_defanged_tg_url(
                message_data.channel_id,
                message_data.channel_name,
                telegram_msg_id
            )
            if defanged_url:
                message_data.metadata['src_url_defanged'] = defanged_url

    def _is_image_file(self, file_path: str) -> bool:
        """Check if a file is an image based on its extension.

        Args:
            file_path: Path to the file to check

        Returns:
            bool: True if the file has an image extension, False otherwise
        """
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
        file_ext = os.path.splitext(file_path)[1].lower()
        return file_ext in image_extensions

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
        if any_destination_has_restricted_mode and message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_media and message_data.original_message:
            # _is_media_restricted returns True if media IS restricted, so invert for "passes" check
            media_passes_restrictions = not self.telegram._is_media_restricted(message_data.original_message)

        if message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_media and not message_data.media_path:
            should_download_media = False
            for destination in destinations:
                if destination['type'] in (APP_TYPE_DISCORD, APP_TYPE_TELEGRAM):
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
        if destination['type'] == APP_TYPE_DISCORD:
            content = self.discord.format_message(parsed_message, destination)
            status = await self._send_to_discord(parsed_message, destination, content, include_media)
        elif destination['type'] == APP_TYPE_TELEGRAM:
            content = self.telegram.format_message(parsed_message, destination)
            status = await self._send_to_telegram(parsed_message, destination, content, include_media)
        else:
            status = "failed"

        _logger.info(f"[Watchtower] Message from {parsed_message.channel_name} by {parsed_message.username} {status} to {destination['name']}")

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

        # Check file size limit before sending
        if media_path:
            content, should_send_media = self._check_file_size_and_modify_content(
                content, media_path, self.discord.file_size_limit, destination
            )
            media_path = media_path if should_send_media else None

        success = self.discord.send_message(content, destination['discord_webhook_url'], media_path)

        if success:
            self.metrics.increment("messages_sent_discord")
            if parsed_message.ocr_raw:
                self.metrics.increment("ocr_msgs_sent")
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

        # Check file size limit before sending
        if media_path:
            content, should_send_media = self._check_file_size_and_modify_content(
                content, media_path, self.telegram.file_size_limit, destination
            )
            media_path = media_path if should_send_media else None

        channel_specifier = destination['telegram_dst_channel']

        destination_chat_id = await self.telegram.resolve_destination(channel_specifier)
        if destination_chat_id is None:
            _logger.warning(f"[TelegramHandler] Skipping unresolved destination: {channel_specifier}")
            return "failed"

        try:
            ok = await self.telegram.send_copy(destination_chat_id, content, media_path)
            if ok:
                self.metrics.increment("messages_sent_telegram")
                if parsed_message.ocr_raw:
                    self.metrics.increment("ocr_msgs_sent")
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
            _logger.error(f"[TelegramHandler] Failed to send to {channel_specifier}: {e}")
            return "failed"

    def _extract_matched_lines_from_attachment(self, media_path: str, keywords: List[str]) -> dict:
        """Extract lines from attachment file that match keywords, or first N lines if no keywords.

        Streams the file line-by-line to avoid loading large files into memory.
        If keywords are provided, returns matching lines. If no keywords, returns first 100 lines.

        Args:
            media_path: Path to the attachment file
            keywords: List of keywords to match against (empty list = no keywords)

        Returns:
            dict: {
                'matched_lines': List of lines (matched or first N),
                'total_lines': Total number of lines in file,
                'is_sample': True if showing first N lines due to no keywords
            }
        """
        result = {
            'matched_lines': [],
            'total_lines': 0,
            'is_sample': False
        }

        if not media_path:
            return result

        try:
            path = Path(media_path)
            if not path.exists():
                return result

            # Check if file has a supported text extension
            from AllowedFileTypes import ALLOWED_EXTENSIONS
            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                return result

            # Stream file line-by-line (never load entire file into memory)
            matched_lines = []
            total_lines = 0

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    line_stripped = line.rstrip('\n\r')

                    if keywords:
                        # Keywords provided - check for matches
                        if any(keyword.lower() in line_stripped.lower() for keyword in keywords):
                            matched_lines.append(line_stripped)
                    else:
                        # No keywords - collect first 100 lines as sample
                        if total_lines <= 100:
                            matched_lines.append(line_stripped)

            result['matched_lines'] = matched_lines
            result['total_lines'] = total_lines
            result['is_sample'] = (len(keywords) == 0)

            return result

        except Exception as e:
            _logger.warning(f"[Watchtower] Failed to extract lines from {media_path}: {e}")
            return result

    def _check_file_size_and_modify_content(
        self,
        content: str,
        media_path: Optional[str],
        file_size_limit: int,
        destination: Dict
    ) -> tuple[str, bool]:
        """Check if attachment exceeds file size limit and modify content if needed.

        If the attachment file exceeds the destination's file size limit, extracts
        the lines that matched keywords (or first 100 lines if no keywords) and appends
        them to the message content with block quote formatting. The media should then be skipped.

        Args:
            content: Formatted message content (Discord markdown or Telegram HTML)
            media_path: Path to attachment file (or None)
            file_size_limit: Maximum file size in bytes for this destination
            destination: Destination config with keywords and type

        Returns:
            tuple[str, bool]: (modified_content, should_include_media)
                modified_content: Content with matched/sampled lines appended if file too large
                should_include_media: False if file too large, True otherwise
        """
        if not media_path:
            return content, False

        try:
            file_size = Path(media_path).stat().st_size

            if file_size <= file_size_limit:
                return content, True

            # File is too large - extract matched lines or sample
            file_size_mb = file_size / (1024 * 1024)
            _logger.info(
                f"[Watchtower] Attachment {Path(media_path).name} ({file_size_mb:.1f}MB) "
                f"exceeds limit ({file_size_limit / (1024*1024):.1f}MB), streaming file for keyword extraction"
            )

            keywords = destination.get('keywords', [])
            result = self._extract_matched_lines_from_attachment(media_path, keywords)

            matched_lines = result['matched_lines']
            total_lines = result['total_lines']
            is_sample = result['is_sample']
            dest_type = destination.get('type', 'discord')

            if matched_lines:
                # Format header based on whether it's a sample or keyword matches
                if is_sample:
                    # No keywords configured - showing first N lines as sample
                    header = f"Attachment too large to forward ({file_size_mb:.0f} MB). No keywords configured, showing first {len(matched_lines)} lines:"
                else:
                    # Keywords matched - showing matched lines
                    header = f"Attachment too large to forward ({file_size_mb:.0f} MB). Matched {len(matched_lines)} line(s):"

                # Format lines with block quotes based on destination type
                if dest_type == APP_TYPE_TELEGRAM:
                    # Telegram uses HTML blockquote tags
                    from html import escape
                    lines_escaped = [escape(line) for line in matched_lines]
                    lines_formatted = f"<blockquote>{'<br>'.join(lines_escaped)}</blockquote>"
                    attachment_section = f"\n\n<b>{escape(header)}</b>\n{lines_formatted}"
                else:
                    # Discord uses markdown quote prefix ("> ")
                    lines_quoted = [f"> {line}" for line in matched_lines]
                    attachment_section = f"\n\n**{header}**\n" + "\n".join(lines_quoted)

                # Add file statistics
                if dest_type == APP_TYPE_TELEGRAM:
                    attachment_section += f"\n\n<i>[Full file has {total_lines:,} lines]</i>"
                else:
                    attachment_section += f"\n\n*[Full file has {total_lines:,} lines]*"

                content += attachment_section
            else:
                # Empty file or no lines extracted
                if dest_type == APP_TYPE_TELEGRAM:
                    content += f"\n\n<b>[Attachment too large to forward ({file_size_mb:.0f} MB), file appears empty]</b>"
                else:
                    content += f"\n\n**[Attachment too large to forward ({file_size_mb:.0f} MB), file appears empty]**"

            return content, False

        except Exception as e:
            _logger.error(f"[Watchtower] Error checking file size for {media_path}: {e}")
            return content, True  # On error, try to send normally

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

def main():
    """Main entry point for Watchtower CLI.

    Parses command-line arguments and dispatches to appropriate subcommand:
    - monitor: Run live message monitoring and routing
    - discover: Auto-generate config from accessible Telegram channels
    """
    parser = argparse.ArgumentParser(description="Watchtower - CTI Message Routing")
    subparsers = parser.add_subparsers(dest="cmd")

    # monitor subcommand
    monitor_parser = subparsers.add_parser("monitor", help="Run live monitoring/forwarding")
    monitor_parser.add_argument("--sources", default="all", help="Comma-separated: telegram,rss,all (default: all)")

    # discover subcommand
    discover_parser = subparsers.add_parser("discover", help="Auto-generate config from accessible Telegram channels")
    discover_parser.add_argument("--diff", action="store_true", help="Compare with existing config (shows new and removed channels)")
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
            _logger.info("[Watchtower] Interrupted by user (Ctrl+C)")
            if app:
                asyncio.run(app.shutdown())
        except Exception as e:
            _logger.error(f"[Watchtower] Fatal error: {e}")
            if app:
                asyncio.run(app.shutdown())
            raise

    elif args.cmd == "discover":
        try:
            asyncio.run(discover_channels(diff_mode=args.diff, generate_config=args.generate))
        except KeyboardInterrupt:
            _logger.info("[Discover] Cancelled by user")
        except Exception as e:
            _logger.error(f"[Discover] Error: {e}", exc_info=True)
            raise

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
