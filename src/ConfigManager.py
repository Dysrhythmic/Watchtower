"""
ConfigManager - Configuration loading and validation

This module loads and validates configuration from multiple sources:
- Environment variables (config/.env file): Telegram API credentials and destination channels, Discord webhook URLs, JSON configuration file path
- JSON configuration file (defaults to config/config.json): Maps destinations to sources, configuration options for each source
- Keyword files (config/*.json): JSON files with keyword lists for filtering

Configuration Structure:
    config/
    ├── .env                    # Environment variables
    ├── config.json             # Main configuration
    ├── kw-general.json         # Keyword list (example)
    └── kw-work.json            # Keyword list (example)

Features:
- Validates required environment variables on startup
- Flexible destination configuration (currently supports: Discord webhooks, Telegram channels)
- Keyword files and inline keyword lists can be used in combination
- Source-specific settings per destination (OCR, restricted mode, keywords, etc.)

Configuration Flow:
    1. Load environment variables from .env
    2. Parse config.json destinations array
    3. For each destination:
        a. Resolve webhook URL or Telegram channel from environment variables
        b. Load channel source configurations
        c. Load RSS feed configurations
        d. Resolve keyword file references
    4. Build internal data structures:
        - destinations list: ALL destination configs (Discord webhooks, Telegram channels)
        - rss_feeds list: Unique RSS feed sources, deduplicated so each is only polled once when routed to multiple destinations

Deduplication strategy:
- Keywords: Deduplicated per source via sets in _resolve_keywords()
- RSS feeds: Deduplicated URLs via storing as dictionary keys in _load_config()
- Telegram channels: Deduplication via sets in get_all_channel_ids()
"""

import os
import json
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path
from LoggerSetup import setup_logger
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD, APP_TYPE_SLACK, APP_TYPE_RSS

_logger = setup_logger(__name__)

class ConfigManager:
    """Manages configuration from environment variables and JSON configuration files.

    Loads and validates configuration on initialization:
    - Validates environment variables based on configured destination/source types
    - Validates destination types and endpoints
    - Validates keyword file formats
    - Validates parser options
    - Assumes default values for boolean options (e.g., ocr, check_attachments, and restricted_mode)
    """

    def __init__(self, load_full_config=True):
        """Initialize by loading environment variables and optionally the full configuration.

        Args:
            load_full_config: If True (default), loads and validates config.json.
                            If False, only loads env vars and paths (minimal mode for discover).

        Raises:
            ValueError: If required environment variables are missing or config is invalid (when load_full_config=True)
        """
        # Project directory structure (Watchtower/)
        self.project_root = Path(__file__).resolve().parents[1]

        # Resolve config dir (Watchtower/config)
        self.config_dir = Path(__file__).resolve().parents[1] / "config"

        # Load .env file (Watchtower/config/.env) into environment
        self.env_path = self.config_dir / ".env"
        load_dotenv(dotenv_path=self.env_path)

        # Load Telegram API credentials from environment (validated later based on usage)
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')

        # Create temporary working directories if they don't exist
        self.tmp_dir = self.project_root / "tmp"
        self.attachments_dir = self.tmp_dir / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.rsslog_dir = self.tmp_dir / "rsslog"
        self.rsslog_dir.mkdir(parents=True, exist_ok=True)
        self.telegramlog_dir = self.tmp_dir / "telegramlog"
        self.telegramlog_dir.mkdir(parents=True, exist_ok=True)

        # Keyword file cache to avoid re-parsing files used by multiple destinations
        self._keyword_cache: Dict[str, List[str]] = {}

        # Expose CONFIG_FILE env var
        self.config_file = os.getenv('CONFIG_FILE', 'config.json')

        # Load and validate full configuration if requested
        if load_full_config:
            config_path = self.config_dir / self.config_file
            self.destinations, self.rss_feeds = self._load_config(config_path)
            self._validate_env_config()

            # Channel ID -> Channel Name mapping
            self.channel_names: Dict[str, str] = {}

            _logger.info(f"Loaded {len(self.destinations)} destinations and {len(self.rss_feeds)} RSS feeds")
        else:
            # Minimal mode:
            self.destinations = []
            self.rss_feeds = []
            self.channel_names = {}
            _logger.info("Initialized in minimal mode (env vars and paths only)")

    def _validate_env_config(self):
        """Validate required environment configuration (credentials, webhooks).

        This method checks which destination types and source types are configured,
        then validates that the necessary environment variables are available.

        Raises:
            ValueError: If required environment variables are missing for configured destination/source types
        """
        telegram_used = False
        discord_used = False
        discord_webhooks_valid = False
        slack_used = False
        slack_webhooks_valid = False
        destination_types_found = set()

        for destination in self.destinations:
            dest_type = destination.get('type')
            destination_types_found.add(dest_type)

            if dest_type == APP_TYPE_TELEGRAM:
                telegram_used = True
            elif dest_type == APP_TYPE_DISCORD:
                discord_used = True
                # Check if this Discord destination has a webhook URL
                if destination.get('discord_webhook_url'):
                    discord_webhooks_valid = True
            elif dest_type == APP_TYPE_SLACK:
                slack_used = True
                # Check if this Slack destination has a webhook URL
                if destination.get('slack_webhook_url'):
                    slack_webhooks_valid = True

            # Check if any sources are Telegram channels
            for channel in destination.get('channels', []):
                if channel.get('source_type') == APP_TYPE_TELEGRAM:
                    telegram_used = True

        # Check for Telegram API ID/hash if Telegram is used as a destination or source
        if telegram_used:
            if not self.api_id or not self.api_hash:
                raise ValueError(
                    "Telegram is configured but missing required credentials: TELEGRAM_API_ID, TELEGRAM_API_HASH. "
                    "Add these to your .env file or remove Telegram destinations/sources from your config."
                )
            _logger.info("Telegram API credentials validated")

        # Check for Discord webhooks if Discord is used as a destination
        if discord_used:
            if not discord_webhooks_valid:
                raise ValueError(
                    "Discord destinations are configured but no webhook URLs were found. "
                    "Check that the environment variables for Discord webhooks are set correctly in your .env file."
                )
            _logger.info("Discord webhook URLs validated")

        # Check for Slack webhooks if Slack is used as a destination
        if slack_used:
            if not slack_webhooks_valid:
                raise ValueError(
                    "Slack destinations are configured but no webhook URLs were found. "
                    "Check that the environment variables for Slack webhooks are set correctly in your .env file."
                )
            _logger.info("Slack webhook URLs validated")

        if not destination_types_found:
            raise ValueError(
                "No destination types found. "
                "Check that there is at least one destination in your config file."
            )

    def _load_config(self, config_file: Path) -> tuple[List[Dict], List[Dict]]:
        """Load and validate configuration file.

        Parses JSON configuration file and processes each destination entry.

        Args:
            config_file: Path to config.json

        Returns:
            tuple[List[Dict], List[Dict]]: (destinations, rss_feeds)
                - destinations: List of all destination configurations
                - rss_feeds: List of unique RSS feed URLs and their names for RSSHandler to poll and log

        Raises:
            ValueError: If config file not found or no valid destinations configured
        """
        if not config_file.exists():
            raise ValueError(f"Config file {config_file} not found")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        destinations: List[Dict] = []
        # Use dict for RSS deduplication: {rss_url: rss_name}
        rss_feed_index: Dict[str, str] = {}

        destination_list = config.get('destinations', [])

        for destination_config in destination_list:
            result = self._process_destination_config(destination_config, rss_feed_index)
            if result:
                destinations.append(result)

        if not destinations:
            raise ValueError("No valid destinations configured")

        # Check for duplicate destination names
        destination_names = [d['name'] for d in destinations]
        duplicates = [name for name in destination_names if destination_names.count(name) > 1]
        if duplicates:
            unique_duplicates = set(duplicates)
            _logger.warning(
                f"Duplicate destination names: {', '.join(unique_duplicates)}. "
                f"This may cause confusion in logs."
            )

        # Convert RSS feed index to list
        rss_feeds = [{'rss_url': url, 'rss_name': name} for url, name in rss_feed_index.items()]

        return destinations, rss_feeds

    def _process_destination_config(self, destination_config: Dict, rss_feed_index: Dict[str, str]) -> Optional[Dict]:
        """Process a single destination configuration entry."""
        name = destination_config.get('name', 'Unnamed')
        dest_type = destination_config.get('type')

        # Destination must be an expected type
        if dest_type not in [APP_TYPE_DISCORD, APP_TYPE_TELEGRAM, APP_TYPE_SLACK]:
            _logger.error(f"Invalid or missing destination type for '{name}': {dest_type}.")
            return None

        endpoint = self._resolve_destination_endpoint(destination_config, name, dest_type)
        if endpoint is None:
            return None

        telegram_channels = self._process_telegram_channel_sources(destination_config, name)
        if telegram_channels is None:
            return None

        self._process_rss_sources(destination_config, name, telegram_channels, rss_feed_index)

        # Destination must have at least one source
        if not telegram_channels: # RSS feeds will be in this list as well as "pseudo Telegram channels"
            _logger.error(f"Destination {name} has no sources")
            return None

        # Build destination entry (applicable to all destination types)
        entry = {
            'name': name,
            'type': dest_type,
            'channels': telegram_channels  # Contains Telegram channels + RSS pseudo-channels
        }

        # Add type-specific destination endpoint
        if dest_type == APP_TYPE_DISCORD:
            entry['discord_webhook_url'] = endpoint
        elif dest_type == APP_TYPE_SLACK:
            entry['slack_webhook_url'] = endpoint
        elif dest_type == APP_TYPE_TELEGRAM:
            entry['telegram_dst_channel'] = endpoint

        return entry

    def _resolve_destination_endpoint(self, destination_config: Dict, name: str, dest_type: str) -> Optional[str]:
        """Resolve destination endpoint from environment variable.

        Resolves the endpoint for a destination type by reading the env_key:
        - Discord: env_key contains webhook URL (e.g., https://discord.com/api/webhooks/...)
        - Telegram: env_key contains channel ID (e.g., "@channel_username" or "-1001234567890")
        - Future destination types: env_key contains appropriate endpoint identifier

        Args:
            destination_config: Destination configuration dictionary
            name: Destination name (for logging)
            dest_type: Destination type (discord, telegram, etc.)

        Returns:
            Optional[str]: The endpoint URL/channel ID, or None if configuration is invalid
        """
        if 'env_key' not in destination_config:
            _logger.warning(f"No env_key specified for {dest_type} destination {name}")
            return None

        endpoint = os.getenv(destination_config['env_key'])
        if not endpoint:
            _logger.warning(f"Missing environment variable {destination_config['env_key']} for {dest_type} destination {name}")
            return None

        return endpoint

    def _validate_parser_config(self, parser: Dict, source_id: str, dest_name: str, config_dict: Dict) -> None:
        """Validate parser configuration for a source.

        Args:
            parser: Parser configuration dictionary
            source_id: ID of the source (channel ID or RSS name for logging)
            dest_name: Destination name (for logging)
            config_dict: The source config dict to modify (parser may be removed if invalid)
        """
        if not parser or not isinstance(parser, dict):
            return

        has_keep = 'keep_first_lines' in parser
        has_trim = 'trim_front_lines' in parser or 'trim_back_lines' in parser

        # Check mutual exclusivity
        if has_keep and has_trim:
            _logger.error(
                f"{source_id}: "
                f"Parser cannot use 'keep_first_lines' with 'trim_front_lines'/'trim_back_lines'. "
                f"Ignoring trim options for {dest_name}"
            )
            parser.pop('trim_front_lines', None)
            parser.pop('trim_back_lines', None)
            has_trim = False  # Update flag after removing trim options

        # Validate keep_first_lines value (if present, must be non-negative integer)
        if has_keep:
            keep = parser.get('keep_first_lines', 0)
            if not isinstance(keep, int) or keep <= 0:
                _logger.warning(
                    f"{source_id}: "
                    f"'keep_first_lines' must be a positive integer, got {keep}. Parser disabled for {dest_name}"
                )
                config_dict.pop('parser', None)
                return

        # Validate trim values (if present, must be non-negative integers)
        if has_trim:
            trim_front = parser.get('trim_front_lines', 0)
            trim_back = parser.get('trim_back_lines', 0)

            if not isinstance(trim_front, int) or trim_front < 0:
                _logger.warning(
                    f"{source_id}: "
                    f"'trim_front_lines' must be a non-negative integer, got {trim_front}. Parser disabled for {dest_name}"
                )
                config_dict.pop('parser', None)
            elif not isinstance(trim_back, int) or trim_back < 0:
                _logger.warning(
                    f"{source_id}: "
                    f"'trim_back_lines' must be a non-negative integer, got {trim_back}. Parser disabled for {dest_name}"
                )
                config_dict.pop('parser', None)

    def _process_telegram_channel_sources(self, destination_config: Dict, name: str) -> Optional[List[Dict]]:
        """Process Telegram channel sources and resolve their keywords.

        For each Telegram channel source, resolves keyword configuration (files + inline keywords),
        deduplicates them, and logs settings like restricted_mode and OCR.

        Args:
            destination_config: Destination configuration dict with 'channels' key containing Telegram channel configs
            name: Destination name (for logging purposes)

        Returns:
            List of processed Telegram channel dicts with resolved keywords, or None if invalid
        """
        telegram_channels = destination_config.get('channels', [])
        if not telegram_channels:
            return []

        if not all('id' in channel for channel in telegram_channels):
            _logger.warning(f"Invalid telegram channels for {name}")
            return None

        processed_telegram_channels = []
        for telegram_channel in telegram_channels:
            # Create a copy and resolve keywords
            processed_channel = dict(telegram_channel)
            processed_channel['keywords'] = self._resolve_keywords(telegram_channel.get('keywords'))
            processed_channel['source_type'] = APP_TYPE_TELEGRAM

            if not processed_channel['keywords']:
                _logger.info(
                    f"{processed_channel['id']}: "
                    f"No keywords configured, all messages will be forwarded to {name}"
                )

            self._validate_parser_config(
                processed_channel.get('parser'),
                processed_channel['id'],
                name,
                processed_channel
            )

            processed_telegram_channels.append(processed_channel)

            # Log settings
            if processed_channel.get('restricted_mode', False):
                _logger.info(f"Restricted mode enabled for channel {processed_channel['id']} for {name}")

            if processed_channel.get('ocr', False):
                _logger.info(f"OCR enabled for channel {processed_channel['id']} for {name}")

            if not processed_channel.get('check_attachments', True): # defaults to True rather than False
                _logger.info(f"Attachment checking disabled for channel {processed_channel['id']} for {name}")

            if processed_channel.get('parser'):
                parser = processed_channel['parser']
                if 'keep_first_lines' in parser:
                    _logger.info(f"Parser for {processed_channel['id']}: keep first {parser['keep_first_lines']} lines for {name}")
                elif 'trim_front_lines' in parser or 'trim_back_lines' in parser:
                    front = parser.get('trim_front_lines', 0)
                    back = parser.get('trim_back_lines', 0)
                    # Only log if there's actual trimming happening
                    if front > 0 or back > 0:
                        _logger.info(f"Parser for {processed_channel['id']}: trim front={front}, back={back} for {name}")

        return processed_telegram_channels

    def _process_rss_sources(self, destination_config: Dict, dest_name: str, telegram_channels: List[Dict], rss_feed_index: Dict[str, str]):
        """Process RSS feed sources and add them as pseudo-channels to Telegram channels list.

        RSS feeds are treated as "pseudo-channels" so they can be added to the same channels list
        as Telegram sources to more easily allow both Telegram and RSS sources to use the same
        filtering/routing infrastructure.

        RSS feeds are deduplicated by URL across all destinations. Each unique feed is polled once,
        then routed to all destinations that want it.

        Args:
            destination_config: Destination configuration dict with 'rss' key
            dest_name: Destination name (for logging)
            telegram_channels: Telegram channels list to append RSS pseudo-channels to (modified in-place)
            rss_feed_index: RSS feed deduplication index (modified in-place)
        """
        rss_sources = destination_config.get('rss', [])
        for rss_entry in rss_sources:
            rss_url = rss_entry.get('url')
            if not rss_url:
                _logger.warning(f"RSS entry missing URL in {dest_name}")
                continue

            # Add to RSS feed deduplication index if not already present
            if rss_url not in rss_feed_index:
                rss_feed_index[rss_url] = rss_entry.get('name', rss_url)

            # Create pseudo-channel for routing using URLs as the channel IDs
            rss_channel = {
                'id': rss_url,
                'keywords': self._resolve_keywords(rss_entry.get('keywords')),
                'parser': rss_entry.get('parser'),
                'source_type': APP_TYPE_RSS
            }

            rss_name = rss_entry.get('name', rss_url)
            self._validate_parser_config(
                rss_channel.get('parser'),
                f"RSS:{rss_name}",
                dest_name,
                rss_channel
            )

            telegram_channels.append(rss_channel)

            # Log RSS settings
            rss_name = rss_entry.get('name', rss_url)
            if not rss_channel['keywords']:
                _logger.info(
                    f"RSS:{rss_name}: "
                    f"No keywords configured, all items will be forwarded to {dest_name}"
                )

            if rss_channel.get('parser'):
                parser = rss_channel['parser']
                if 'keep_first_lines' in parser:
                    _logger.info(f"Parser for RSS:{rss_name}: keep first {parser['keep_first_lines']} lines for {dest_name}")
                elif 'trim_front_lines' in parser or 'trim_back_lines' in parser:
                    front = parser.get('trim_front_lines', 0)
                    back = parser.get('trim_back_lines', 0)
                    # Only log if there's actual trimming happening
                    if front > 0 or back > 0:
                        _logger.info(f"Parser for RSS:{rss_name}: trim front={front}, back={back} for {dest_name}")

    def _load_keyword_file(self, filename: str) -> List[str]:
        """Load keywords from a JSON file in the config directory.

        JSON format is used (rather than plain text) because:
        - Whitespaces are more visible in quotes: " breach" vs "breach",
          which can help avoid false positives (e.g., " 0 day " won't match "10 days")
        - Extensible for future metadata (e.g., keyword weight, categories, regex flags, etc.)

        Expected JSON format:
        {
            "keywords": ["keyword1", "keyword2", "keyword3"]
        }

        Args:
            filename: Name of the keyword file (e.g., 'kw-hackertools.json')

        Returns:
            List[str]: List of keyword strings (not deduplicated at this stage)

        Raises:
            ValueError: If file doesn't exist or has invalid format
        """
        # Check cache first
        if filename in self._keyword_cache:
            return self._keyword_cache[filename]

        # Assumes path is in config directory
        kw_file = self.config_dir / filename

        if not kw_file.exists():
            raise ValueError(f"Keyword file not found: {filename}")

        try:
            with open(kw_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in keyword file {filename}: {e}")

        if 'keywords' not in data:
            raise ValueError(f"Invalid keyword file format in {filename}: missing 'keywords' key")

        keywords = data['keywords']
        if not isinstance(keywords, list):
            raise ValueError(f"Invalid keyword file format in {filename}: 'keywords' must be an array")

        if not all(isinstance(kw, str) for kw in keywords):
            raise ValueError(f"Invalid keyword file format in {filename}: all keywords must be strings")

        # Cache and return
        self._keyword_cache[filename] = keywords
        _logger.debug(f"Loaded {len(keywords)} keywords from {filename}")
        return keywords

    def _resolve_keywords(self, keyword_config) -> List[str]:
        """Resolve keywords from config (files + inline).

        Args:
            keyword_config: Either None or a dict with 'files' and/or 'inline' keywords

        Returns:
            List of resolved keyword strings (empty list means to forward all messages)

        Raises:
            ValueError: If format is invalid
        """
        # None -> forward all messages
        if keyword_config is None:
            return []

        # Must be a dictionary
        if not isinstance(keyword_config, dict):
            raise ValueError(f"Invalid keyword format: expected dict with 'files' and/or 'inline' keys, got {type(keyword_config).__name__}")

        keywords = []

        # Load from files
        files = keyword_config.get('files', [])
        if files:
            if not isinstance(files, list):
                raise ValueError("'files' must be an array of filenames")
            for filename in files:
                if not isinstance(filename, str):
                    raise ValueError(f"Invalid filename in 'files': expected string, got {type(filename).__name__}")
                keywords.extend(self._load_keyword_file(filename))

        # Add inline keywords
        inline = keyword_config.get('inline', [])
        if inline:
            if not isinstance(inline, list):
                raise ValueError("'inline' must be an array of keywords")
            if not all(isinstance(kw, str) for kw in inline):
                raise ValueError("All keywords in 'inline' must be strings")
            keywords.extend(inline)

        # Deduplicate keywords
        keywords = list(set(keywords))

        return keywords

    def get_all_channel_ids(self) -> Set[str]:
        """Get all unique Telegram channel IDs from destination config.

        Collects all Telegram channel IDs across all destinations, excluding RSS feeds.
        Uses the 'source_type' field to differentiate between Telegram channels
        and RSS pseudo-channels.

        Returns:
            Set[str]: Unique Telegram channel IDs
        """
        telegram_channel_ids = set()
        for destination in self.destinations:
            for channel in destination['channels']:
                if channel.get('source_type') == APP_TYPE_TELEGRAM:
                    telegram_channel_ids.add(channel['id'])
        return telegram_channel_ids
