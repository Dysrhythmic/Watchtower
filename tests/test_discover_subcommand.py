import unittest
import sys
import os
import json
import tempfile
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from Watchtower import discover_channels


class TestDiscoverSubcommand(unittest.TestCase):
    """Test the discover subcommand functionality."""

    def setUp(self):
        """Create temporary directory for test configs."""
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.test_dir) / "config"
        self.config_dir.mkdir()

        # Create .env file with mock credentials
        env_path = self.config_dir / ".env"
        with open(env_path, 'w') as f:
            f.write("TELEGRAM_API_ID=123456\n")
            f.write("TELEGRAM_API_HASH=abc123def456\n")

    def tearDown(self):
        """Clean up temporary directory."""
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch('telethon.TelegramClient')
    @patch('os.getenv')
    def test_discover_generate_creates_config_file(self, mock_getenv, mock_telegram_client):
        """
        Test that discover --generate properly creates config_discovered.json.

        Verifies:
        - Config file is created
        - Has correct structure (destinations array)
        - Contains discovered channels
        - Has proper default settings per channel
        """
        # Mock environment variables
        def getenv_side_effect(key):
            if key == 'TELEGRAM_API_ID':
                return '123456'
            elif key == 'TELEGRAM_API_HASH':
                return 'abc123def456'
            return None
        mock_getenv.side_effect = getenv_side_effect

        # Mock TelegramClient
        mock_client = MagicMock()
        mock_telegram_client.return_value = mock_client

        # Mock client.start() to be async
        async def mock_start():
            pass
        mock_client.start = mock_start

        # Mock client.disconnect() to be async
        async def mock_disconnect():
            pass
        mock_client.disconnect = mock_disconnect

        # Create mock dialogs (channels)
        mock_channel1 = Mock()
        mock_channel1.title = "Test Channel 1"
        mock_channel1.username = "testchannel1"
        mock_channel1.broadcast = True
        mock_channel1.megagroup = False

        mock_channel2 = Mock()
        mock_channel2.title = "Test Group"
        mock_channel2.username = "testgroup"
        mock_channel2.broadcast = False
        mock_channel2.megagroup = True

        # Create mock User (bot)
        mock_bot = Mock()
        mock_bot.bot = True
        mock_bot.username = "testbot"
        mock_bot.first_name = "Test Bot"
        mock_bot.last_name = None
        mock_bot.is_self = False

        # Create mock dialogs
        mock_dialog1 = Mock()
        mock_dialog1.entity = mock_channel1
        mock_dialog1.id = -1001234567890

        mock_dialog2 = Mock()
        mock_dialog2.entity = mock_channel2
        mock_dialog2.id = -1009876543210

        mock_dialog3 = Mock()
        mock_dialog3.entity = mock_bot
        mock_dialog3.id = 123456789

        # Mock get_dialogs() to be async and return dialogs
        async def mock_get_dialogs():
            return [mock_dialog1, mock_dialog2, mock_dialog3]

        mock_client.get_dialogs = mock_get_dialogs

        # Patch __file__ in Watchtower module to point to our test directory
        # This makes Path(__file__).resolve().parents[1] naturally resolve to test_dir
        fake_watchtower_path = str(Path(self.test_dir) / "src" / "Watchtower.py")

        with patch('Watchtower.__file__', fake_watchtower_path):
            # Run discover with generate flag
            asyncio.run(discover_channels(diff_mode=False, generate_config=True))

        # Verify config file was created
        config_file = self.config_dir / "config_discovered.json"
        self.assertTrue(config_file.exists(),
            "config_discovered.json should be created")

        # Load and verify config structure
        with open(config_file, 'r') as f:
            config = json.load(f)

        # Verify top-level structure
        self.assertIn('destinations', config,
            "Config should have 'destinations' key")
        self.assertIsInstance(config['destinations'], list,
            "'destinations' should be a list")
        self.assertGreater(len(config['destinations']), 0,
            "Should have at least one destination")

        # Verify destination structure
        dest = config['destinations'][0]
        self.assertIn('name', dest)
        self.assertIn('type', dest)
        self.assertIn('env_key', dest)
        self.assertIn('channels', dest)

        # Verify channels array
        channels = dest['channels']
        self.assertIsInstance(channels, list)
        self.assertGreater(len(channels), 0,
            "Should have discovered channels")

        # Verify channel structure
        for channel in channels:
            self.assertIn('id', channel,
                "Channel should have 'id' field")
            self.assertIn('keywords', channel,
                "Channel should have 'keywords' field")
            self.assertIn('restricted_mode', channel,
                "Channel should have 'restricted_mode' field")
            self.assertIn('parser', channel,
                "Channel should have 'parser' field")
            self.assertIn('ocr', channel,
                "Channel should have 'ocr' field")

            # Verify default values
            self.assertFalse(channel['restricted_mode'],
                "Default restricted_mode should be False")
            self.assertFalse(channel['ocr'],
                "Default OCR should be False")
            self.assertEqual(channel['parser']['trim_front_lines'], 0,
                "Default parser trim_front_lines should be 0")
            self.assertEqual(channel['parser']['trim_back_lines'], 0,
                "Default parser trim_back_lines should be 0")

    @patch('telethon.TelegramClient')
    @patch('os.getenv')
    def test_discover_without_generate_no_file_created(self, mock_getenv, mock_telegram_client):
        """
        Test that discover without --generate flag does NOT create config file.

        This ensures the flag is respected and users aren't surprised by
        unwanted file creation.
        """
        # Mock environment variables
        def getenv_side_effect(key):
            if key == 'TELEGRAM_API_ID':
                return '123456'
            elif key == 'TELEGRAM_API_HASH':
                return 'abc123def456'
            return None
        mock_getenv.side_effect = getenv_side_effect

        # Mock TelegramClient
        mock_client = MagicMock()
        mock_telegram_client.return_value = mock_client

        # Mock async methods
        async def mock_start():
            pass
        mock_client.start = mock_start

        async def mock_disconnect():
            pass
        mock_client.disconnect = mock_disconnect

        # Mock empty dialogs
        async def mock_get_dialogs():
            return []
        mock_client.get_dialogs = mock_get_dialogs

        # Patch __file__ in Watchtower module to point to our test directory
        fake_watchtower_path = str(Path(self.test_dir) / "src" / "Watchtower.py")

        with patch('Watchtower.__file__', fake_watchtower_path):
            # Run discover WITHOUT generate flag
            asyncio.run(discover_channels(diff_mode=False, generate_config=False))

        # Verify config file was NOT created
        config_file = self.config_dir / "config_discovered.json"
        self.assertFalse(config_file.exists(),
            "config_discovered.json should NOT be created without --generate flag")


class TestDiscoverConfigFormat(unittest.TestCase):
    """Test that discover generates config in the correct new format."""

    def test_generated_config_uses_destinations_format(self):
        """
        Verify generated config uses new 'destinations' format, not old 'webhooks' format.

        Old format (deprecated):
        {
            "webhooks": [...]
        }

        New format (correct):
        {
            "destinations": [{
                "name": "...",
                "type": "discord",
                "env_key": "...",
                "channels": [...]
            }]
        }
        """
        from Watchtower import _save_discovered_config

        # Create temporary directory
        test_dir = tempfile.mkdtemp()
        config_dir = Path(test_dir)

        try:
            # Create mock channels
            channels = [
                {
                    "name": "Test Channel",
                    "type": "Channel",
                    "info": {
                        "id": "@testchannel",
                        "keywords": {"files": [], "inline": []},
                        "restricted_mode": False,
                        "parser": {"trim_front_lines": 0, "trim_back_lines": 0},
                        "ocr": False
                    }
                }
            ]

            # Generate config
            _save_discovered_config(channels, config_dir)

            # Load generated config
            config_file = config_dir / "config_discovered.json"
            with open(config_file, 'r') as f:
                config = json.load(f)

            # Verify new format
            self.assertIn('destinations', config,
                "Config should use 'destinations' key (new format)")
            self.assertNotIn('webhooks', config,
                "Config should NOT use 'webhooks' key (old format)")

            # Verify destination has required fields
            dest = config['destinations'][0]
            self.assertEqual(dest['type'], 'discord',
                "Default type should be 'discord'")
            self.assertEqual(dest['env_key'], 'DISCORD_WEBHOOK_URL',
                "Default env_key should be 'DISCORD_WEBHOOK_URL'")

        finally:
            # Cleanup
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
