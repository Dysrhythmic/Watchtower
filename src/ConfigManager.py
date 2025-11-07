"""
ConfigManager - Configuration loading and validation

This module loads and validates configuration from multiple sources:
- Environment variables (config/.env file): Telegram API credentials and destination channels, Discord webhook URLs, JSON configuration file path
- JSON configuration file (defaults to config/config.json): Maps destinations to sources, configure options for each source
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
- Keyword files can be combined with inline keyword lists
- RSS feed deduplication (same URL used by multiple destinations)
- Source-specific settings per destination (OCR, restricted mode, parsers, keywords)

Configuration Flow:
    1. Load environment variables from .env
    2. Parse config.json destinations array
    3. For each destination:
        a. Resolve webhook URL or Telegram channel from env vars
        b. Load channel source configurations
        c. Load RSS feed configurations
        d. Resolve keyword file references
    4. Build internal data structures:
        - destinations list: ALL destination configs (Discord webhooks, Telegram channels)
        - rss_feeds list: Unique RSS feed sources (deduplicated by URL)
"""
import os
import json
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path
from logger_setup import setup_logger

# Project directory structure (Watchtower/)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Resolve config dir (Watchtower/config)
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Load .env file (Watchtower/config/.env) into environment
_ENV_PATH = _CONFIG_DIR / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

_logger = setup_logger(__name__)


class ConfigManager:
    """Manages configuration from environment variables and JSON configuration files.

    Loads and validates configuration on initialization:
    - Validates required environment variables (Telegram API credentials)
    - Validates destination types (must be 'discord' or 'telegram')
    - Validates destination endpoints (env vars must exist and be non-empty)
    - Validates keyword file formats (JSON structure, data types)

    Current limitations:
    - Does NOT validate for duplicate destination names
    - Does NOT validate all optional field values
    - Does NOT validate Telegram channel ID formats beyond basic presence checks
    """

    def __init__(self):
        """Initialize by loading all configuration sources and creating temporary working directories.

        Raises:
            ValueError: If required environment variables are missing or config is invalid
        """
        # Load Telegram API credentials from environment
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')

        if not self.api_id or not self.api_hash:
            raise ValueError("Missing required: TELEGRAM_API_ID, TELEGRAM_API_HASH")

        # Create temporary working directories if they don't exist
        self.tmp_dir = _PROJECT_ROOT / "tmp"
        self.attachments_dir = self.tmp_dir / "attachments"     # Downloaded media files
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.rsslog_dir = self.tmp_dir / "rsslog"               # RSS feed timestamp logs for polling
        self.rsslog_dir.mkdir(parents=True, exist_ok=True)
        self.telegramlog_dir = self.tmp_dir / "telegramlog"     # Telegram message ID logs for polling
        self.telegramlog_dir.mkdir(parents=True, exist_ok=True)

        # Keyword file cache: filename -> List[keywords]
        # Avoid re-parsing keyword files when multiple destinations use same one
        self._keyword_cache: Dict[str, List[str]] = {}

        # Load and parse configuration file
        # CONFIG_FILE env var can override default config.json
        config_filename = os.getenv('CONFIG_FILE', 'config.json')
        config_path = _CONFIG_DIR / config_filename
        self.destinations, self.rss_feeds = self._load_config(config_path)

        # Channel ID -> channel name mapping
        self.channel_names: Dict[str, str] = {}

        _logger.info(f"[ConfigManager] Loaded {len(self.destinations)} destinations and {len(self.rss_feeds)} RSS feeds")

    def _load_config(self, config_file: Path) -> tuple[List[Dict], List[Dict]]:
        """Load and validate configuration file.

        Parses JSON configuration file and processes each destination entry.

        Deduplication strategy:
        - Keywords: Deduplicated per source via list(set()) in _resolve_keywords()
        - RSS feeds: Deduplicated globally by URL (same feed polled once, routed to multiple destinations)
        - Telegram channels: NOT deduplicated (same channel can legitimately appear in multiple destinations)

        Args:
            config_file: Path to config.json

        Returns:
            tuple[List[Dict], List[Dict]]: (destinations, rss_feeds)
                - destinations: List of ALL destination configurations (Discord webhooks, Telegram channels, etc.)
                - rss_feeds: List of unique RSS feed configurations

        Raises:
            ValueError: If config file not found or no valid destinations configured
        """
        if not config_file.exists():
            raise ValueError(f"Config file {config_file} not found")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        destinations: List[Dict] = [] # <-- review: should this be called destinations instead of destinations?
        # Use dict for RSS deduplication: {rss_url: {rss_name, rss_url}}
        rss_feed_index: Dict[str, Dict] = {}

        destination_list = config.get('destinations', [])

        for destination_config in destination_list:
            result = self._process_destination_config(destination_config, rss_feed_index)
            if result:
                destinations.append(result)

        if not destinations:
            raise ValueError("[ConfigManager] No valid destinations configured")

        # Convert RSS feed index to list (deduplicated by URL)
        rss_feeds = list(rss_feed_index.values())

        return destinations, rss_feeds

    def _process_destination_config(self, destination_config: Dict, rss_feed_index: Dict[str, Dict]) -> Optional[Dict]:
        """Process a single destination configuration entry."""
        name = destination_config.get('name', 'Unnamed')
        dest_type = destination_config.get('type')

        # Validate destination type - must be explicitly specified
        if dest_type not in ['discord', 'telegram']:
            _logger.error(f"[ConfigManager] Invalid or missing destination type for '{name}': {dest_type}. Must be 'discord' or 'telegram'")
            return None

        # Resolve destination endpoint
        discord_webhook_url, telegram_dst_channel = self._resolve_destination_endpoint(destination_config, name, dest_type)
        if discord_webhook_url is None and telegram_dst_channel is None:
            return None

        # Process Telegram channel sources
        telegram_channels = self._process_telegram_channel_sources(destination_config, name)
        if telegram_channels is None:
            return None

        # Process RSS sources (adds to global deduplication index)
        # Note: RSS feeds are added as pseudo-channels to the telegram_channels list for unified routing
        self._process_rss_sources(destination_config, name, telegram_channels, rss_feed_index)

        # Must have at least one source (Telegram channel or RSS feed)
        if not telegram_channels:
            _logger.warning(f"[ConfigManager] Destination {name} has no sources (telegram channels or rss)")
            return None

        # Build destination entry (applicable to all destination types)
        entry = {
            'name': name,
            'type': dest_type,
            'channels': telegram_channels  # Contains Telegram channels + RSS pseudo-channels
        }
        # Add type-specific destination endpoint
        # Note: Different key names provide clarity about endpoint types:
        # - 'discord_webhook_url': Discord uses stateless webhooks (URL is the endpoint)
        # - 'telegram_destination_channel': Telegram uses stateful bot API (channel ID is the destination)
        if dest_type == 'discord':
            entry['discord_webhook_url'] = discord_webhook_url
        else:  # telegram
            entry['telegram_destination_channel'] = telegram_dst_channel

        return entry

    def _resolve_destination_endpoint(self, destination_config: Dict, name: str, dest_type: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve Discord webhook URL or Telegram destination channel from environment variables.

        Both Discord and Telegram use env_key to reference environment variable names:
        - Discord: env_key contains webhook URL (e.g., https://discord.com/api/webhooks/...)
        - Telegram: env_key contains channel ID in one of two formats:
            * Username format: "@channel_username" (e.g., "@my_channel")
            * Numeric ID format: "-1001234567890" (channel ID, typically negative for supergroups)

        Returns:
            tuple[Optional[str], Optional[str]]: (discord_webhook_url, telegram_channel_id)
                - Returns (url, None) for Discord destinations
                - Returns (None, channel_id) for Telegram destinations
                - Returns (None, None) if configuration is invalid or env var missing
        """
        if dest_type == 'discord':
            if 'env_key' in destination_config:
                discord_webhook_url = os.getenv(destination_config['env_key'])
                if not discord_webhook_url:
                    _logger.warning(f"[ConfigManager] Missing environment variable {destination_config['env_key']} for {name}")
                    return None, None
                return discord_webhook_url, None
            else:
                _logger.warning(f"[ConfigManager] No env_key for Discord webhook {name}")
                return None, None

        elif dest_type == 'telegram':
            if 'env_key' in destination_config:
                channel_id = os.getenv(destination_config['env_key'])
                if not channel_id:
                    _logger.warning(f"[ConfigManager] Missing environment variable {destination_config['env_key']} for {name}")
                    return None, None
                return None, channel_id
            else:
                _logger.warning(f"[ConfigManager] No env_key specified for Telegram destination {name}")
                return None, None

        else:
            _logger.warning(f"[ConfigManager] Unknown destination type for {name}: {dest_type}")
            return None, None

    def _process_telegram_channel_sources(self, destination_config: Dict, name: str) -> Optional[List[Dict]]:
        """Process Telegram channel sources and resolve their keywords.

        For each Telegram channel source, resolves keyword configuration (files + inline keywords),
        deduplicates them, and logs special settings like restricted_mode and OCR.

        Note: This method is specific to Telegram channels. Future platform integrations
        (Discord channels, Slack, etc.) would have their own processing methods.

        Args:
            destination_config: Destination configuration dict with 'channels' key containing Telegram channel configs
            name: Destination name (for logging purposes, NOT the Telegram channel name)

        Returns:
            List of processed Telegram channel dicts with resolved keywords, or None if invalid
        """
        telegram_channels = destination_config.get('channels', [])
        if not telegram_channels:
            return []

        if not all('id' in channel for channel in telegram_channels):
            _logger.warning(f"[ConfigManager] Invalid telegram channels for {name}")
            return None

        # Resolve keywords for each Telegram channel
        processed_telegram_channels = []
        for telegram_channel in telegram_channels:
            # Create a copy and resolve keywords (returns List[str], deduplicated)
            processed_channel = dict(telegram_channel)
            processed_channel['keywords'] = self._resolve_keywords(telegram_channel.get('keywords'))
            processed_telegram_channels.append(processed_channel)

            # Log special settings
            if processed_channel.get('restricted_mode', False):
                _logger.info(f"[ConfigManager] Restricted mode enabled for channel {processed_channel['id']}")
            if processed_channel.get('ocr', False):
                _logger.info(f"[ConfigManager] OCR enabled for channel {processed_channel['id']}")

        return processed_telegram_channels

    def _process_rss_sources(self, destination_config: Dict, dest_name: str, telegram_channels: List[Dict], rss_feed_index: Dict[str, Dict]):
        """Process RSS feed sources and add them as pseudo-channels to Telegram channels list.

        RSS feeds are treated as "pseudo-channels" - they're added to the same channels list
        as Telegram sources to enable unified message routing logic. This allows both Telegram
        and RSS sources to use the same filtering/routing infrastructure.

        RSS feeds are deduplicated globally by URL. Each unique feed is polled once,
        then routed to all destinations that want it. Each destination can specify different
        keywords/parsers for the same RSS feed, which is why RSS entries are added per-destination.

        Args:
            destination_config: Destination configuration dict with 'rss' key
            dest_name: Destination name (for logging)
            telegram_channels: Telegram channels list to append RSS pseudo-channels to (modified in-place
                              for efficiency - avoids creating new list and concatenation overhead)
            rss_feed_index: Global RSS feed deduplication index (modified in-place to track unique feeds)
        """
        rss_sources = destination_config.get('rss', [])
        for rss_entry in rss_sources:
            rss_url = rss_entry.get('url')
            if not rss_url:
                _logger.warning(f"[ConfigManager] RSS entry missing URL in {dest_name}")
                continue

            # Add to global RSS feed deduplication index if not already present
            if rss_url not in rss_feed_index:
                rss_feed_index[rss_url] = {
                    'rss_name': rss_entry.get('name', rss_url),
                    'rss_url': rss_url
                }

            # Create pseudo-channel for routing
            # Each destination can have different keywords/parsers for the same RSS feed URL
            # Note: RSS feed URLs are used as the ID for RSS sources
            rss_channel = {
                'id': rss_url,
                'keywords': self._resolve_keywords(rss_entry.get('keywords')),
                'parser': rss_entry.get('parser')
            }
            telegram_channels.append(rss_channel)

    def _load_keyword_file(self, filename: str) -> List[str]:
        """Load keywords from a JSON file in the config directory.

        JSON format provides structured data and allows for future extensions
        (e.g., keyword metadata, categories). Alternative formats like plain text
        (one keyword per line) could be simpler but less extensible.

        Expected JSON format:
        {
            "keywords": ["keyword1", "keyword2", ...]
        }

        Args:
            filename: Name of the keyword file (e.g., 'kw-general.json')

        Returns:
            List[str]: List of keyword strings (not deduplicated at this stage)

        Raises:
            ValueError: If file doesn't exist or has invalid format
        """
        # Check cache first
        if filename in self._keyword_cache:
            return self._keyword_cache[filename]

        # Resolve path relative to config directory
        kw_file = _CONFIG_DIR / filename

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

        # Cache and return (deduplication happens in _resolve_keywords)
        self._keyword_cache[filename] = keywords
        _logger.debug(f"[ConfigManager] Loaded {len(keywords)} keywords from {filename}")
        return keywords

    def _resolve_keywords(self, keyword_config) -> List[str]:
        """Resolve keywords from config (files + inline).

        Args:
            keyword_config: Either None or a dict with 'files' and/or 'inline' keywords

        Returns:
            List of resolved keyword strings (empty list = forward all messages)

        Raises:
            ValueError: If format is invalid
        """
        # None = forward all messages
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

        # Deduplicate keywords using set conversion
        # Note: Stored as List[str] throughout (not Set[str]) because:
        # - Order might matter for some matching algorithms
        # - Lists are more commonly used in JSON config
        # - Deduplication at resolution time is efficient enough
        keywords = list(set(keywords))

        return keywords

    def get_all_channel_ids(self) -> Set[str]:
        """Get all unique Telegram channel IDs from destination config.

        Collects all Telegram channel IDs across all destinations, excluding RSS feeds.
        RSS feeds are identified by URLs starting with 'http://' or 'https://'.

        Note: This fragile detection (checking URL prefix) could be improved by:
        - Adding an explicit 'source_type' field to channel dicts
        - Using source type constants (SOURCE_TYPE_TELEGRAM, SOURCE_TYPE_RSS)

        Returns:
            Set[str]: Unique Telegram channel IDs (usernames like @channel or numeric IDs like -1001234567890)
        """
        telegram_channel_ids = set()
        for destination in self.destinations:
            for channel in destination['channels']:
                channel_id = channel['id']
                # Exclude RSS feeds (identified by HTTP/HTTPS URLs)
                if not channel_id.startswith('http://') and not channel_id.startswith('https://'):
                    telegram_channel_ids.add(channel_id)
        return telegram_channel_ids
