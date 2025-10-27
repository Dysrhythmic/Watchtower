import logging
import os
import json
from typing import List, Dict, Set
from dotenv import load_dotenv
from pathlib import Path

# Resolve config dir
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
        
        # Load webhook configuration
        config_path = _CONFIG_DIR / "config.json"
        self.webhooks = self._load_webhooks(config_path)
        self.channel_names = {}  # channel_id -> friendly name mapping for display/logging
        
        logger.info(f"[ConfigManager] Loaded {len(self.webhooks)} webhooks")

        # Get project root
        self.project_root = Path(__file__).resolve().parents[1]
        # Create attachments/ directory
        self.attachments_dir = self.project_root / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    
    def _load_webhooks(self, config_file: str) -> List[Dict]:
        """Load and validate webhook configuration."""
        if not os.path.exists(config_file):
            raise ValueError(f"Config file {config_file} not found")
        
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        webhooks = []
        for webhook in config.get('webhooks', []):
            name = webhook.get('name', 'Unnamed')
            
            # Resolve webhook URL
            if 'env_key' in webhook:
                url = os.getenv(webhook['env_key'])
                if not url:
                    logger.warning(f"[ConfigManager] Missing environment variable {webhook['env_key']} for {name}")
                    continue
            elif 'url' in webhook:
                url = webhook['url']
            else:
                logger.warning(f"[ConfigManager] No URL for webhook {name}")
                continue
            
            # Validate channels
            channels = webhook.get('channels', [])
            if not channels or not all('id' in channel for channel in channels):
                logger.warning(f"[ConfigManager] Invalid channels for webhook {name}")
                continue
            
            # Log restricted mode settings for channels
            for channel in channels:
                if channel.get('restricted_mode', False):
                    logger.info(f"[ConfigManager] Restricted mode enabled for channel {channel['id']}")
            
            webhooks.append({
                'name': name,
                'url': url,
                'channels': channels
            })
        
        if not webhooks:
            raise ValueError("[ConfigManager] No valid webhooks configured")
        
        return webhooks
    
    def get_all_channel_ids(self) -> Set[str]:
        """Get all unique channel IDs from webhook config."""
        ids = set()
        for webhook in self.webhooks:
            for channel in webhook['channels']:
                ids.add(channel['id'])
        return ids
