"""
Watchtower - Main orchestrator for message monitoring and routing

This module contains the core Watchtower application that coordinates all components
to monitor message sources and route matching messages to configured destinations
based on keywords and filters.

Subcommands:
    monitor: Run live message monitoring and routing
        --sources: Comma-separated sources (telegram, rss, or all)

    discover: Auto-generate config from accessible Telegram channels
        --diff: Compare discovered channels with existing configuration
        --generate: Create config_discovered.json file based on discovered channels
"""
from __future__ import annotations
import os
import argparse
import asyncio
import json
import time
from typing import List, Dict, Optional, TYPE_CHECKING
from pathlib import Path
from LoggerSetup import setup_logger
from Discover import discover_channels
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD, APP_TYPE_SLACK, APP_TYPE_RSS
from AllowedFileTypes import ALLOWED_EXTENSIONS
from SendStatus import SendStatus

if TYPE_CHECKING:
    from MessageData import MessageData

_logger = setup_logger(__name__)

class Watchtower:
    """Main application orchestrator for message monitoring.

    Coordinates all components to monitor message sources and route
    matching messages to configured destinations based on keyword filtering
    and per-destination configuration.

    Attributes:
        config: ConfigManager for loading and validating application configuration
        telegram: TelegramHandler for Telegram operations
        discord: DiscordHandler for Discord operations
        slack: SlackHandler for Slack operations
        router: MessageRouter for keyword matching and routing
        ocr: OCRHandler for text extraction from images
        message_queue: MessageQueue for retry handling
        metrics: MetricsCollector for usage statistics
        sources: List of enabled sources
        rss: RSSHandler instance (created if RSS is enabled)
    """

    def __init__(self,
                 sources: List[str],
                 config = None,
                 telegram = None,
                 discord = None,
                 slack = None,
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
            slack: SlackHandler instance (or None to create default)
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
        from SlackHandler import SlackHandler
        from OCRHandler import OCRHandler
        from MessageQueue import MessageQueue
        from MetricsCollector import MetricsCollector

        # Use provided instances for dependency injection or create defaults
        self.config = config or ConfigManager()
        self.metrics = metrics or MetricsCollector(self.config.tmp_dir / "metrics.json")
        self.telegram = telegram or TelegramHandler(self.config, self.metrics)
        self.router = router or MessageRouter(self.config)
        self.discord = discord or DiscordHandler()
        self.slack = slack or SlackHandler()
        self.ocr = ocr or OCRHandler()
        self.message_queue = message_queue or MessageQueue(self.metrics)

        self.sources = sources
        self.rss = None  # created only if RSS is enabled
        self._shutdown_requested = False
        self._start_time = None  # Track application runtime

        # Clean up any potential attachment files from previous runs
        self._cleanup_attachments_dir()

        _logger.info("Initialized")

    def _cleanup_attachments_dir(self):
        """Remove any leftover attachments from previous runs.

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
                            _logger.info(f"Cleaned up leftover file: {file_path}")
                    except Exception as e:
                        _logger.warning(f"Failed to clean up {file_path}: {e}")
                _logger.info(f"Cleaned up {len(files)} leftover media files from attachments directory")

    async def start(self) -> None:
        """Start the Watchtower service.

        Initializes all configured sources and their handlers,
        starts the message queue processor for retries,
        and keeps the service running.

        Returns:
            None
        """
        self._start_time = time.time()
        tasks = []

        # Start message queue processor (background retry task)
        tasks.append(asyncio.create_task(self.message_queue.process_queue(self)))

        if APP_TYPE_TELEGRAM in self.sources:
            await self.telegram.start()
            self.telegram.setup_handlers(self._handle_message)
            # Connection proofs
            await self.telegram.fetch_latest_messages()
            tasks.append(asyncio.create_task(self.telegram.run()))
            # Start polling for missed messages
            tasks.append(asyncio.create_task(self.telegram.poll_missed_messages()))

        if APP_TYPE_RSS in self.sources and self.config.rss_feeds:
            from RSSHandler import RSSHandler
            self.rss = RSSHandler(self.config, self._handle_message)
            for feed in self.config.rss_feeds:
                tasks.append(asyncio.create_task(self.rss.run_feed(feed)))

        _logger.info(f"Now monitoring for new messages... (sources={','.join(self.sources)})")

        if tasks:
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                _logger.info("Tasks cancelled, returning to main...")

    async def shutdown(self):
        """Gracefully shutdown the application.

        Stops all sources, disconnects clients, saves metrics.

        Returns:
            None
        """
        _logger.info("Initiating graceful shutdown...")
        self._shutdown_requested = True

        if self._start_time is not None:
            runtime_seconds = int(time.time() - self._start_time)
            self.metrics.set("seconds_ran", runtime_seconds)

        self.metrics.force_save()

        metrics_summary = self.metrics.get_all()
        if metrics_summary:
            _logger.info(
                f"Final metrics for this session:\n"
                f"{json.dumps(metrics_summary, indent=2)}"
            )

        queue_size = self.message_queue.get_queue_size()
        if queue_size > 0:
            _logger.warning(f"Shutting down with {queue_size} messages in retry queue (will be lost)")

        if self.telegram:
            self._clear_telegram_logs()

        if self.telegram and self.telegram.client.is_connected():
            await self.telegram.client.disconnect()
            _logger.info("Telegram client disconnected")

        _logger.info("Shutdown complete")

    def _clear_telegram_logs(self):
        """Clear all Telegram log files on shutdown.

        Removes all .txt files in the tmp/telegramlog/ directory. Telegram logs are
        not persistent across restarts to avoid processing messages sent during downtime.

        Called during shutdown to prevent stale log files from affecting next startup.
        Errors during cleanup are logged but shutdown continues
        """
        try:
            telegramlog_dir = self.config.telegramlog_dir
            if telegramlog_dir.exists():
                count = 0
                for log_file in telegramlog_dir.glob("*.txt"):
                    log_file.unlink()
                    count += 1
                _logger.info(f"Cleared {count} telegram log file(s)")
        except Exception as e:
            _logger.error(f"Error clearing telegram logs: {e}")

    async def _handle_message(self, message_data: 'MessageData', is_latest: bool) -> bool:
        """Process incoming message

        Central message processing pipeline that:
        1. Handles initial connection proof logging
        2. Pre-processes message (OCR, URL defanging)
        3. Routes to matching destinations via MessageRouter
        4. Checks media restrictions for each destination
        5. Dispatches message to each destination
        6. Tracks metrics and handles errors
        7. Cleans up stored attachment files

        Args:
            message_data: Incoming message from Telegram or RSS source
            is_latest: If True, this is a connection proof message (not routed)

        Returns:
            bool: True if message was successfully routed to at least one destination,
                  False if no destinations matched or all deliveries failed
        """
        try:
            # Connection proof logging
            if is_latest:
                _logger.info(
                    f"\nCONNECTION ESTABLISHED\n"
                    f"  Channel: {message_data.channel_name}\n"
                    f"  Latest message by: {message_data.username}\n"
                    f"  Time: {message_data.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                )
                return False

            # Track incoming messages by source
            self.metrics.increment(f"messages_received_{message_data.source_type.lower()}")

            await self._preprocess_message(message_data)

            destinations = self.router.get_destinations(message_data)
            if not destinations:
                _logger.info(f"Message from {message_data.channel_name} by {message_data.username} has no destinations")
                self.metrics.increment("total_msgs_no_destination")
                return False

            attachment_passes_restrictions = await self._handle_attachment_restrictions(message_data, destinations)

            success_count = 0
            for destination in destinations:
                success = await self._dispatch_to_destination(message_data, destination, attachment_passes_restrictions)
                if success:
                    success_count += 1

            if success_count > 0:
                self.metrics.increment("total_msgs_routed_success")
            else:
                self.metrics.increment("total_msgs_routed_failed")

            return success_count > 0

        except Exception as e:
            _logger.error(f"Error processing message from {message_data.channel_name} by {message_data.username}: {e}", exc_info=True)
            return False

        finally:
            # Clean up stored attachments after all destinations have been processed
            if message_data.attachment_path and os.path.exists(message_data.attachment_path):
                try:
                    os.remove(message_data.attachment_path)
                    _logger.debug(f"Cleaned up stored attachment file: {message_data.attachment_path}")
                except Exception as e:
                    _logger.error(f"Error removing stored attachment file at {message_data.attachment_path}: {e}")

    async def _preprocess_message(self, message_data: MessageData):
        """Pre-process message with OCR and defanged URLs

        Defanged URLs make t.me links non-clickable (hxxps://t[.]me format) to prevent
        accidental navigation to potentially malicious content
        """
        ocr_needed = False
        if message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_attachments:
            ocr_needed = self.router.is_ocr_enabled_for_channel(message_data.channel_id, message_data.channel_name, message_data.source_type)
        if ocr_needed and self.ocr.is_available():
            if not message_data.attachment_path:
                message_data.attachment_path = await self.telegram.download_attachment(message_data)
            if message_data.attachment_path and os.path.exists(message_data.attachment_path):
                # Only attempt OCR on image files
                if self._is_image_file(message_data.attachment_path):
                    ocr_text = self.ocr.extract_text(message_data.attachment_path)
                    if ocr_text:
                        message_data.ocr_enabled = True
                        message_data.ocr_raw = ocr_text
                        self.metrics.increment("ocr_msgs_processed")
                else:
                    _logger.debug(f"Skipping OCR for non-image file: {message_data.attachment_path}")

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
        image_extensions = {'.jpg', '.jpeg', 'jfif', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}
        file_ext = os.path.splitext(file_path)[1].lower()
        return file_ext in image_extensions

    async def _handle_attachment_restrictions(self, message_data: MessageData, destinations: List[Dict]) -> bool:
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

        attachment_passes_restrictions = True
        if any_destination_has_restricted_mode and message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_attachments and message_data.original_message:
            # _is_media_restricted returns True if media IS restricted, so invert for "passes" check
            attachment_passes_restrictions = not self.telegram._is_attachment_restricted(message_data.original_message)

        if message_data.source_type == APP_TYPE_TELEGRAM and message_data.has_attachments and not message_data.attachment_path:
            should_download_attachment = False
            for destination in destinations:
                if destination['type'] in (APP_TYPE_DISCORD, APP_TYPE_TELEGRAM):
                    if not destination.get('restricted_mode', False):
                        should_download_attachment = True
                        break
                    elif attachment_passes_restrictions:
                        should_download_attachment = True
                        break
            if should_download_attachment:
                message_data.attachment_path = await self.telegram.download_attachment(message_data)

        return attachment_passes_restrictions

    async def _dispatch_to_destination(self, message_data: MessageData, destination: Dict, attachment_passes_restrictions: bool) -> bool:
        """Dispatch message to a single destination

        Applies destination specific parsing, formats the message, determines media inclusion,
        and routes to the appropriate sending method based on destination type

        Args:
            message_data: The message to send
            destination: Destination configuration (contains type, parser, restricted_mode, etc.)
            attachment_passes_restrictions: Whether media passed restricted mode checks

        Returns:
            bool: True if sent successfully to at least one destination, False otherwise
        """
        parsed_message = self.router.parse_msg(message_data, destination['parser'])

        include_attachment = False
        if parsed_message.attachment_path:
            if not destination.get('restricted_mode', False) or attachment_passes_restrictions:
                include_attachment = True

        if destination['type'] == APP_TYPE_DISCORD:
            content = self.discord.format_message(parsed_message, destination)
            status = await self._send_to_discord(parsed_message, destination, content, include_attachment)
        elif destination['type'] == APP_TYPE_SLACK:
            content = self.slack.format_message(parsed_message, destination)
            status = await self._send_to_slack(parsed_message, destination, content, include_attachment)
        elif destination['type'] == APP_TYPE_TELEGRAM:
            content = self.telegram.format_message(parsed_message, destination)
            status = await self._send_to_telegram(parsed_message, destination, content, include_attachment)
        else:
            status = SendStatus.FAILED

        _logger.info(f"Message from {parsed_message.channel_name} by {parsed_message.username} {status.value} to {destination['name']}")

        return status == SendStatus.SENT

    async def _send_to_discord(self, parsed_message: MessageData, destination: Dict, content: str, include_attachment: bool) -> SendStatus:
        """Send message to Discord webhook.

        Appends a note if media was blocked by restricted mode, then sends via HTTP POST.

        Args:
            parsed_message: The parsed message with applied parser rules
            destination: Discord webhook destination config
            content: Formatted message text
            include_attachment: Whether to include media attachment

        Returns:
            SendStatus: SENT if successful, QUEUED if enqueued for retry, FAILED otherwise
        """
        if parsed_message.has_attachments and not include_attachment:
            if destination.get('restricted_mode', False):
                content += "\n**[Media attachment filtered due to restricted mode]**"
            else:
                content += f"\n**[Media type {parsed_message.attachment_type} could not be forwarded to Discord]**"

        attachment_path = parsed_message.attachment_path if include_attachment else None

        if attachment_path:
            content, should_send_attachment = self._check_file_size_and_modify_content(
                content, attachment_path, self.discord.file_size_limit, destination, parsed_message
            )
            attachment_path = attachment_path if should_send_attachment else None

        success = await self.discord.send_message(content, destination['discord_webhook_url'], attachment_path)

        if success:
            self.metrics.increment("messages_sent_discord")
            if parsed_message.ocr_raw:
                self.metrics.increment("ocr_msgs_sent")
            return SendStatus.SENT
        else:
            self.message_queue.enqueue(
                destination=destination,
                formatted_content=content,
                attachment_path=attachment_path,
                reason="Discord send failed (likely rate limit)"
            )
            self.metrics.increment("messages_queued_retry")
            return SendStatus.QUEUED

    async def _send_to_slack(self, parsed_message: MessageData, destination: Dict, content: str, include_attachment: bool) -> SendStatus:
        """Send message to Slack webhook.

        Args:
            parsed_message: The parsed message with applied parser rules
            destination: Slack webhook destination config
            content: Formatted message text
            include_attachment: Whether to include media attachment (will show warning instead)

        Returns:
            SendStatus: SENT if successful, QUEUED if enqueued for retry, FAILED otherwise
        """
        if parsed_message.has_attachments and not include_attachment:
            if destination.get('restricted_mode', False):
                content += "\n*[Media attachment filtered due to restricted mode]*"
            else:
                content += f"\n*[Media type {parsed_message.attachment_type} could not be forwarded to Slack]*"

        # Slack webhooks don't support attachments, so we pass the attachment_path
        # to trigger the warning message in send_message, but the file won't be sent
        attachment_path = parsed_message.attachment_path if include_attachment else None

        success = await self.slack.send_message(content, destination['slack_webhook_url'], attachment_path)

        if success:
            self.metrics.increment("messages_sent_slack")
            if parsed_message.ocr_raw:
                self.metrics.increment("ocr_msgs_sent")
            return SendStatus.SENT
        else:
            self.message_queue.enqueue(
                destination=destination,
                formatted_content=content,
                attachment_path=None,  # Don't retry with attachment since Slack webhooks don't support it
                reason="Slack send failed (likely rate limit)"
            )
            self.metrics.increment("messages_queued_retry")
            return SendStatus.QUEUED

    async def _send_to_telegram(self, parsed_message: MessageData, destination: Dict, content: str, include_attachment: bool) -> SendStatus:
        """Send message to Telegram channel

        Args:
            parsed_message: The parsed message with applied parser rules
            destination: Telegram destination config
            content: Formatted message text
            include_attachment: Whether to include media attachment

        Returns:
            SendStatus: SENT if successful, QUEUED if enqueued for retry, FAILED otherwise
        """
        attachment_path = self._get_attachment_for_send(parsed_message, destination, include_attachment)

        # Check file size limit before sending
        if attachment_path:
            content, should_send_attachment = self._check_file_size_and_modify_content(
                content, attachment_path, self.telegram.file_size_limit, destination, parsed_message
            )
            attachment_path = attachment_path if should_send_attachment else None

        dst_channel_specifier = destination['telegram_dst_channel'] # as specified in config

        destination_chat_id = await self.telegram.resolve_destination(dst_channel_specifier)
        if destination_chat_id is None:
            _logger.warning(f"Skipping unresolved destination: {dst_channel_specifier}")
            return SendStatus.FAILED

        # Cache resolved chat_id for retry queue to check rate limits
        destination['telegram_dst_id'] = destination_chat_id

        try:
            ok = await self.telegram.send_message(content, destination_chat_id, attachment_path)
            if ok:
                self.metrics.increment("messages_sent_telegram")
                if parsed_message.ocr_raw:
                    self.metrics.increment("ocr_msgs_sent")
                return SendStatus.SENT
            else:
                self.message_queue.enqueue(
                    destination=destination,
                    formatted_content=content,
                    attachment_path=attachment_path,
                    reason="Telegram send failed (likely rate limit)"
                )
                self.metrics.increment("messages_queued_retry")
                return SendStatus.QUEUED
        except Exception as e:
            _logger.error(f"Failed to send to {dst_channel_specifier}: {e}")
            return SendStatus.FAILED

    def _extract_matched_lines_from_attachment(self, attachment_path: str, keywords: List[str]) -> dict:
        """Extract lines from attachment file that match keywords, or first N lines if no keywords.

        Streams the file line-by-line to avoid loading large files into memory.
        If keywords are provided, returns matching lines. If no keywords, returns first 100 lines.

        Args:
            attachment_path: Path to the attachment file
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

        if not attachment_path:
            return result

        try:
            path = Path(attachment_path)
            if not path.exists():
                return result

            if path.suffix.lower() not in ALLOWED_EXTENSIONS:
                return result

            # Stream file line-by-line
            matched_lines = []
            total_lines = 0

            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    total_lines += 1
                    line_stripped = line.rstrip('\n\r')

                    if keywords:
                        # Check for matches
                        if any(keyword.lower() in line_stripped.lower() for keyword in keywords):
                            matched_lines.append(line_stripped)
                    else:
                        # Collect first 100 lines as sample
                        if total_lines <= 100:
                            matched_lines.append(line_stripped)

            result['matched_lines'] = matched_lines
            result['total_lines'] = total_lines
            result['is_sample'] = (len(keywords) == 0)

            return result

        except Exception as e:
            _logger.warning(f"Failed to extract lines from {attachment_path}: {e}")
            return result

    def _check_file_size_and_modify_content(
        self,
        content: str,
        attachment_path: Optional[str],
        file_size_limit: int,
        destination: Dict,
        parsed_message: 'MessageData'
    ) -> tuple[str, bool]:
        """Check if attachment exceeds file size limit and modify content if needed.

        If the attachment file exceeds the destination's file size limit, extracts
        the lines that matched keywords (or first 100 lines if no keywords) and appends
        them to the message content with block quote formatting. The attachment should then be skipped.

        Uses cached attachment info from routing phase if available to avoid re-reading the file.

        Args:
            content: Formatted message content (Discord markdown or Telegram HTML)
            attachment_path: Path to attachment file (or None)
            file_size_limit: Maximum file size in bytes for this destination
            destination: Destination config with keywords and type
            parsed_message: MessageData with metadata that may contain cached attachment info

        Returns:
            tuple[str, bool]: (modified_content, should_include_attachment)
                modified_content: Content with matched/sampled lines appended if file too large
                should_include_attachment: False if file too large, True otherwise
        """
        if not attachment_path:
            return content, False

        try:
            file_size = Path(attachment_path).stat().st_size

            if file_size <= file_size_limit:
                return content, True

            # File is too large, extract matched lines or sample
            file_size_mb = file_size / (1024 * 1024)
            _logger.info(
                f"Attachment {Path(attachment_path).name} ({file_size_mb:.1f}MB) "
                f"exceeds limit ({file_size_limit / (1024*1024):.1f}MB), using cached data or streaming file for keyword extraction"
            )

            keywords = destination.get('keywords', [])

            # Check if already extracted during routing (avoids duplicate file read)
            cached_info = parsed_message.metadata.get('attachment_info')
            if cached_info:
                result = {
                    'matched_lines': cached_info['matched_lines'],
                    'total_lines': cached_info['total_lines'],
                    'is_sample': False  # Routing only extracts matches, not samples
                }
            else:
                # Fallback: read file (shouldn't happen in normal flow after routing)
                result = self._extract_matched_lines_from_attachment(attachment_path, keywords)

            matched_lines = result['matched_lines']
            total_lines = result['total_lines']
            is_sample = result['is_sample']
            dest_type = destination.get('type', 'discord')

            if matched_lines:
                if is_sample:
                    # No keywords configured, showing first N lines as sample
                    header = f"Attachment too large to forward ({file_size_mb:.0f} MB). No keywords configured, showing first {len(matched_lines)} lines:"
                else:
                    # Keywords matched, showing matched lines
                    header = f"Attachment too large to forward ({file_size_mb:.0f} MB). Matched {len(matched_lines)} line(s):"

                # Format lines with block quotes based on destination type
                if dest_type == APP_TYPE_TELEGRAM:
                    # Telegram uses HTML blockquote tags
                    from html import escape
                    lines_escaped = [escape(line) for line in matched_lines]
                    lines_formatted = f"<blockquote>{'<br>'.join(lines_escaped)}</blockquote>"
                    attachment_section = f"\n\n<b>{escape(header)}</b>\n{lines_formatted}"
                elif dest_type == APP_TYPE_DISCORD:
                    # Discord uses markdown quote prefix ("> ")
                    lines_quoted = [f"> {line}" for line in matched_lines]
                    attachment_section = f"\n\n**{header}**\n" + "\n".join(lines_quoted)
                elif dest_type == APP_TYPE_SLACK:
                    # Slack uses markdown quote prefix ("> ") but "*" for bold
                    lines_quoted = [f"> {line}" for line in matched_lines]
                    attachment_section = f"\n\n*{header}*\n" + "\n".join(lines_quoted)

                if dest_type == APP_TYPE_TELEGRAM:
                    attachment_section += f"\n\n<b>[Full file has {total_lines:,} lines]</b>"
                elif dest_type == APP_TYPE_DISCORD:
                    attachment_section += f"\n\n**[Full file has {total_lines:,} lines]**"

                content += attachment_section
            else:
                # Empty file or no lines extracted
                if dest_type == APP_TYPE_TELEGRAM:
                    content += f"\n\n<b>[Attachment too large to forward ({file_size_mb:.0f} MB), file appears empty]</b>"
                elif dest_type == APP_TYPE_DISCORD:
                    content += f"\n\n**[Attachment too large to forward ({file_size_mb:.0f} MB), file appears empty]**"

            return content, False

        except Exception as e:
            _logger.error(f"Error checking file size for {attachment_path}: {e}")
            return content, True  # On error, try to send without attachment

    def _get_attachment_for_send(self, parsed_message: MessageData, destination: Dict, include_attachment: bool) -> Optional[str]:
        """Determine which media file to send based on restricted mode and OCR settings.

        Args:
            parsed_message: The message being sent
            destination: Destination configuration
            include_attachment: Whether media should be included at all

        Returns:
            Path to media file or None if media should not be sent
        """
        if not include_attachment or not parsed_message.attachment_path:
            return None

        if destination.get('restricted_mode', False):
            if destination.get('ocr', False):
                return None
            return None

        return parsed_message.attachment_path

def main():
    """Main entry point for Watchtower CLI.

    Parses command-line arguments and dispatches to appropriate subcommand:
    - monitor: Run live message monitoring and routing
    - discover: Compare config against accessible Telegram channels and/or
                generate a new config from accessible Telegram channels
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
            sources = [APP_TYPE_TELEGRAM, APP_TYPE_RSS]
        else:
            # Map lowercase CLI input to AppTypes constants
            source_map = {
                "telegram": APP_TYPE_TELEGRAM,
                "rss": APP_TYPE_RSS
            }
            sources = [source_map[s] for s in ("telegram", "rss") if s in wanted]

        app = None
        try:
            app = Watchtower(sources)
            asyncio.run(app.start())
        except KeyboardInterrupt:
            _logger.info("Interrupted by user (Ctrl+C)")
            if app:
                asyncio.run(app.shutdown())
        except Exception as e:
            _logger.error(f"Error: {e}")
            if app:
                asyncio.run(app.shutdown())
            raise

    elif args.cmd == "discover":
        try:
            asyncio.run(discover_channels(diff_mode=args.diff, generate_config=args.generate))
        except KeyboardInterrupt:
            _logger.info("Interrupted by user (Ctrl+C)")
        except Exception as e:
            _logger.error(f"Error: {e}", exc_info=True)
            raise

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
