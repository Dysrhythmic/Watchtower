"""
ConfigManager - Configuration loading and validation

This module loads and validates configuration from multiple sources:
- Environment variables (.env file): Telegram API credentials, webhook URLs
- JSON config file (config.json): Destination mappings, channel configs, keyword files
- Keyword files: External JSON files with keyword lists for filtering

Configuration Structure:
    config/
    ├── .env                    # API credentials, webhook URLs (git-ignored)
    ├── config.json             # Main configuration
    ├── kw-general.json         # Keyword lists (example)
    └── kw-work.json

Features:
- Validates required environment variables on startup
- Flexible destination configuration (Discord webhooks, Telegram channels)
- Keyword file references with caching
- RSS feed deduplication (same URL used by multiple destinations)
- Per-destination channel-specific settings (OCR, restricted mode, parsers)

Configuration Flow:
    1. Load environment variables from .env
    2. Parse config.json destinations array
    3. For each destination:
        a. Resolve webhook URL or Telegram channel from env vars
        b. Load channel source configurations
        c. Load RSS feed configurations
        d. Resolve keyword file references
    4. Build internal data structures (webhooks list, rss_feeds list)
"""
import os
import json
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path
from logger_setup import setup_logger

# Resolve config dir (always project-root/config)
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Load .env file into environment
_ENV_PATH = _CONFIG_DIR / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

logger = setup_logger(__name__)


class ConfigManager:
    """Manages configuration from environment variables and JSON config files.

    Loads configuration on initialization and validates all required settings.
    Raises ValueError if configuration is invalid or incomplete.
    """

    def __init__(self):
        """Initialize ConfigManager by loading all configuration sources.

        Loads environment variables, parses config.json, validates settings,
        and creates temporary working directories.

        Raises:
            ValueError: If required environment variables are missing or config is invalid
        """
        # Load Telegram API credentials from environment
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')

        if not self.api_id or not self.api_hash:
            raise ValueError("Missing required: TELEGRAM_API_ID, TELEGRAM_API_HASH")

        # Project directory structure
        self.project_root = Path(__file__).resolve().parents[1]

        # Temporary working directories (created if they don't exist)
        self.tmp_dir = self.project_root / "tmp"
        self.attachments_dir = self.tmp_dir / "attachments"  # Downloaded media files
        self.rsslog_dir = self.tmp_dir / "rsslog"  # RSS feed timestamp logs
        self.telegramlog_dir = self.tmp_dir / "telegramlog"  # Telegram message ID logs
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.rsslog_dir.mkdir(parents=True, exist_ok=True)
        self.telegramlog_dir.mkdir(parents=True, exist_ok=True)

        # Keyword file cache: filename -> List[keywords]
        # Avoids re-parsing JSON files when multiple destinations use same keyword file
        self._keyword_cache: Dict[str, List[str]] = {}

        # Load and parse config.json
        config_path = _CONFIG_DIR / "config.json"
        self.webhooks, self.rss_feeds = self._load_config(config_path)

        # Channel ID -> friendly name mapping (populated at runtime)
        self.channel_names: Dict[str, str] = {}

        logger.info(f"[ConfigManager] Loaded {len(self.webhooks)} destinations and {len(self.rss_feeds)} RSS feeds")

    def _load_config(self, config_file: Path) -> tuple[List[Dict], List[Dict]]:
        """Load and validate configuration from config.json.

        Parses JSON configuration file and processes each destination entry.
        Deduplicates RSS feeds (same URL appearing in multiple destinations).

        Args:
            config_file: Path to config.json

        Returns:
            tuple[List[Dict], List[Dict]]: (webhooks, rss_feeds)
                - webhooks: List of destination configurations
                - rss_feeds: List of unique RSS feed configurations

        Raises:
            ValueError: If config file not found or no valid destinations configured
        """
        if not config_file.exists():
            raise ValueError(f"Config file {config_file} not found")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        webhooks: List[Dict] = []
        # Use dict for RSS deduplication: {rss_url: {rss_name, rss_url}}
        rss_feed_index: Dict[str, Dict] = {}

        destination_list = config.get('destinations', [])

        for destination_config in destination_list:
            result = self._process_destination_config(destination_config, rss_feed_index)
            if result:
                webhooks.append(result)

        if not webhooks:
            raise ValueError("[ConfigManager] No valid destinations configured")

        # Convert RSS feed index to list (deduplicated by URL)
        rss_feeds = list(rss_feed_index.values())

        return webhooks, rss_feeds

    def _process_destination_config(self, destination_config: Dict, rss_feed_index: Dict[str, Dict]) -> Optional[Dict]:
        """Process a single destination configuration entry."""
        name = destination_config.get('name', 'Unnamed')
        dest_type = destination_config.get('type', 'discord')

        # Resolve destination endpoint
        discord_webhook_url, telegram_destinations = self._resolve_destination_endpoint(destination_config, name, dest_type)
        if discord_webhook_url is None and telegram_destinations is None:
            return None

        # Process channel sources
        channels = self._process_channel_sources(destination_config, name)
        if channels is None:
            return None

        # Process RSS sources (adds to global deduplication index)
        self._process_rss_sources(destination_config, name, channels, rss_feed_index)

        # Must have at least one source
        if not channels:
            logger.warning(f"[ConfigManager] Destination {name} has no sources (channels or rss)")
            return None

        # Build webhook entry
        entry = {
            'name': name,
            'type': dest_type,
            'channels': channels
        }
        if dest_type == 'discord':
            entry['webhook_url'] = discord_webhook_url
        else:
            entry['destination'] = telegram_destinations

        return entry

    def _resolve_destination_endpoint(self, destination_config: Dict, name: str, dest_type: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve Discord webhook URL or Telegram destination channel.

        Both Discord and Telegram use env_key:
        - Discord: env_key contains webhook URL
        - Telegram: env_key contains single channel ID (e.g., "@channel" or "-1001234567890")
        """
        if dest_type == 'discord':
            if 'env_key' in destination_config:
                discord_webhook_url = os.getenv(destination_config['env_key'])
                if not discord_webhook_url:
                    logger.warning(f"[ConfigManager] Missing environment variable {destination_config['env_key']} for {name}")
                    return None, None
                return discord_webhook_url, None
            else:
                logger.warning(f"[ConfigManager] No env_key for Discord webhook {name}")
                return None, None

        elif dest_type == 'telegram':
            if 'env_key' in destination_config:
                channel_id = os.getenv(destination_config['env_key'])
                if not channel_id:
                    logger.warning(f"[ConfigManager] Missing environment variable {destination_config['env_key']} for {name}")
                    return None, None
                return None, channel_id
            else:
                logger.warning(f"[ConfigManager] No env_key specified for Telegram destination {name}")
                return None, None

        else:
            logger.warning(f"[ConfigManager] Unknown destination type for {name}: {dest_type}")
            return None, None

    def _process_channel_sources(self, destination_config: Dict, name: str) -> Optional[List[Dict]]:
        """Process Telegram channel sources and resolve their keywords.

        For each channel source, resolves keyword configuration (files + inline),
        and logs special settings like restricted_mode and OCR.

        Args:
            destination_config: Destination configuration dict with 'channels' key
            name: Destination name (for logging)

        Returns:
            List of processed channel dicts with resolved keywords, or None if invalid
        """
        channels = destination_config.get('channels', [])
        if not channels:
            return []

        if not all('id' in channel for channel in channels):
            logger.warning(f"[ConfigManager] Invalid channels for {name}")
            return None

        # Resolve keywords for each channel
        processed_channels = []
        for channel in channels:
            # Create a copy and resolve keywords
            processed_channel = dict(channel)
            processed_channel['keywords'] = self._resolve_keywords(channel.get('keywords'))
            processed_channels.append(processed_channel)

            # Log settings
            if processed_channel.get('restricted_mode', False):
                logger.info(f"[ConfigManager] Restricted mode enabled for channel {processed_channel['id']}")
            if processed_channel.get('ocr', False):
                logger.info(f"[ConfigManager] OCR enabled for channel {processed_channel['id']}")

        return processed_channels

    def _process_rss_sources(self, destination_config: Dict, dest_name: str, channels: List[Dict], rss_feed_index: Dict[str, Dict]):
        """Process RSS feed sources and add them to channels list.

        RSS feeds are deduplicated globally by URL. Each unique feed is polled once,
        then routed to all destinations that want it based on per-destination keywords/parser.

        Args:
            destination_config: Destination configuration dict with 'rss' key
            dest_name: Destination name (for logging)
            channels: Channel list to append RSS pseudo-channels to (modified in-place)
            rss_feed_index: Global RSS feed deduplication index (modified in-place)
        """
        rss_sources = destination_config.get('rss', [])
        for rss_entry in rss_sources:
            rss_url = rss_entry.get('url')
            if not rss_url:
                logger.warning(f"[ConfigManager] RSS entry missing URL in {dest_name}")
                continue

            # Add to global RSS feed deduplication index (only if not already present)
            if rss_url not in rss_feed_index:
                rss_feed_index[rss_url] = {
                    'rss_name': rss_entry.get('name', rss_url),
                    'rss_url': rss_url
                }

            # Create pseudo-channel for routing (per-destination keywords/parser)
            # Note: 'id' field contains the RSS URL for RSS sources
            rss_channel = {
                'id': rss_url,
                'keywords': self._resolve_keywords(rss_entry.get('keywords')),
                'parser': rss_entry.get('parser')
            }
            channels.append(rss_channel)

    def _load_keyword_file(self, filename: str) -> List[str]:
        """Load keywords from a JSON file in the config directory.

        Args:
            filename: Name of the keyword file (e.g., 'kw-general.json')

        Returns:
            List of keyword strings

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

        # Cache and return
        self._keyword_cache[filename] = keywords
        logger.debug(f"[ConfigManager] Loaded {len(keywords)} keywords from {filename}")
        return keywords

    def _resolve_keywords(self, keyword_config) -> List[str]:
        """Resolve keywords from config (files + inline).

        Args:
            keyword_config: Either None or a dict with 'files' and/or 'inline' keys

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

        # Deduplicate keywords (simple set-based deduplication)
        keywords = list(set(keywords))

        return keywords

    def get_all_channel_ids(self) -> Set[str]:
        """Get all unique channel IDs from destination config (Telegram sources only).

        Collects all non-RSS channel IDs across all destinations. RSS feeds
        are identified by URLs starting with 'http' and are excluded.

        Returns:
            Set[str]: Unique channel IDs (usernames like @channel or numeric IDs)
        """
        ids = set()
        for webhook in self.webhooks:
            for channel in webhook['channels']:
                channel_id = channel['id']
                if not channel_id.startswith('http'):
                    ids.add(channel_id)
        return ids
