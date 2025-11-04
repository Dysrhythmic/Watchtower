import logging
import os
import json
from typing import List, Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path

# Resolve config dir (always project-root/config)
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Load .env
_ENV_PATH = _CONFIG_DIR / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ConfigManager:
    """Manages configuration from environment variables and JSON config."""

    def __init__(self):
        self.api_id = os.getenv('TELEGRAM_API_ID')
        self.api_hash = os.getenv('TELEGRAM_API_HASH')

        if not self.api_id or not self.api_hash:
            raise ValueError("Missing required: TELEGRAM_API_ID, TELEGRAM_API_HASH")

        # Paths
        self.project_root = Path(__file__).resolve().parents[1]

        # tmp directories at project root
        self.tmp_dir = self.project_root / "tmp"
        self.attachments_dir = self.tmp_dir / "attachments"
        self.rsslog_dir = self.tmp_dir / "rsslog"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.rsslog_dir.mkdir(parents=True, exist_ok=True)

        # Keyword file cache: filename -> List[keywords]
        self._keyword_cache: Dict[str, List[str]] = {}

        # Load config.json
        config_path = _CONFIG_DIR / "config.json"
        self.webhooks, self.rss_feeds = self._load_config(config_path)

        # channel_id -> friendly name mapping for display/logging
        self.channel_names: Dict[str, str] = {}

        logger.info(f"[ConfigManager] Loaded {len(self.webhooks)} destinations and {len(self.rss_feeds)} RSS feeds")

    def _load_config(self, config_file: Path):
        """Load and validate configuration for destinations."""
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
        """Process Telegram channel sources."""
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
        """Get all unique channel IDs from destination config (Telegram sources only)."""
        ids = set()
        for webhook in self.webhooks:
            for channel in webhook['channels']:
                channel_id = channel['id']
                if not channel_id.startswith('http'):
                    ids.add(channel_id)
        return ids
