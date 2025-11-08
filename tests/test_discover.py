"""
Tests for Discover module - Channel discovery functionality

Coverage targets:
- _get_channel_identifier()
- _load_existing_config()
- _calculate_diff()
- _print_diff_output()
- _save_discovered_config()
- discover_channels() (integration test)
"""
import unittest
import json
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from Discover import (
    _get_channel_identifier,
    _load_existing_config,
    _calculate_diff,
    _print_diff_output,
    _save_discovered_config,
    discover_channels
)


class TestGetChannelIdentifier(unittest.TestCase):
    """Test _get_channel_identifier() function."""

    def test_returns_username_when_available(self):
        """
        Given: Entity with username attribute
        When: _get_channel_identifier() called
        Then: Returns @username format
        """
        entity = Mock()
        entity.username = "test_channel"

        result = _get_channel_identifier(entity, 12345)

        self.assertEqual(result, "@test_channel")

    def test_returns_numeric_id_when_no_username(self):
        """
        Given: Entity without username
        When: _get_channel_identifier() called
        Then: Returns numeric dialog ID as string
        """
        entity = Mock()
        entity.username = None

        result = _get_channel_identifier(entity, -1001234567890)

        self.assertEqual(result, "-1001234567890")

    def test_returns_numeric_id_when_username_empty_string(self):
        """
        Given: Entity with empty username string
        When: _get_channel_identifier() called
        Then: Returns numeric dialog ID (treats empty string as falsy)
        """
        entity = Mock()
        entity.username = ""

        result = _get_channel_identifier(entity, 999)

        self.assertEqual(result, "999")

    def test_handles_entity_without_username_attribute(self):
        """
        Given: Entity lacking username attribute entirely
        When: _get_channel_identifier() called
        Then: Returns numeric dialog ID
        """
        entity = Mock(spec=[])  # Empty spec = no attributes

        result = _get_channel_identifier(entity, 12345)

        self.assertEqual(result, "12345")


class TestLoadExistingConfig(unittest.TestCase):
    """Test _load_existing_config() function."""

    def test_loads_valid_config_successfully(self):
        """
        Given: Valid config.json file with channels
        When: _load_existing_config() called
        Then: Returns set of channel IDs and details dict
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_path = config_dir / "config.json"

            # Create test config
            test_config = {
                "destinations": [
                    {
                        "name": "Feed1",
                        "channels": [
                            {"id": "@channel1", "keywords": {}},
                            {"id": "-1001234", "keywords": {}}
                        ]
                    },
                    {
                        "name": "Feed2",
                        "channels": [
                            {"id": "@channel2", "keywords": {}}
                        ]
                    }
                ]
            }

            with open(config_path, 'w') as f:
                json.dump(test_config, f)

            # When: Load config
            with self.assertLogs(level='INFO') as log_context:
                channel_ids, channel_details = _load_existing_config(config_dir)

            # Then: Returns correct channel IDs
            self.assertEqual(channel_ids, {"@channel1", "-1001234", "@channel2"})
            self.assertEqual(len(channel_details), 3)
            self.assertTrue(any("Found 3 existing channels" in msg for msg in log_context.output))

    def test_returns_empty_set_when_no_config_exists(self):
        """
        Given: No config.json file exists
        When: _load_existing_config() called
        Then: Returns empty set and empty dict
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with self.assertLogs(level='INFO') as log_context:
                channel_ids, channel_details = _load_existing_config(config_dir)

            self.assertEqual(channel_ids, set())
            self.assertEqual(channel_details, {})
            self.assertTrue(any("No existing config found" in msg for msg in log_context.output))

    def test_filters_out_http_urls(self):
        """
        Given: Config with both channel IDs and HTTP URLs
        When: _load_existing_config() called
        Then: Returns only channel IDs, excludes HTTP URLs
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_path = config_dir / "config.json"

            test_config = {
                "destinations": [
                    {
                        "name": "Feed",
                        "channels": [
                            {"id": "@channel1", "keywords": {}},
                            {"id": "https://example.com/rss", "keywords": {}},
                            {"id": "http://feed.com", "keywords": {}}
                        ]
                    }
                ]
            }

            with open(config_path, 'w') as f:
                json.dump(test_config, f)

            channel_ids, _ = _load_existing_config(config_dir)

            # Only @channel1 should be included (HTTP URLs filtered out)
            self.assertEqual(channel_ids, {"@channel1"})

    def test_handles_invalid_json(self):
        """
        Given: Malformed JSON config file
        When: _load_existing_config() called
        Then: Returns None, None and logs error
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            config_path = config_dir / "config.json"

            # Write invalid JSON
            with open(config_path, 'w') as f:
                f.write("{ invalid json syntax")

            with self.assertLogs(level='ERROR') as log_context:
                channel_ids, channel_details = _load_existing_config(config_dir)

            self.assertIsNone(channel_ids)
            self.assertIsNone(channel_details)
            self.assertTrue(any("Error loading config" in msg for msg in log_context.output))

    def test_handles_custom_config_filename(self):
        """
        Given: Custom config filename
        When: _load_existing_config() called with custom filename
        Then: Loads from custom file
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            custom_path = config_dir / "custom_config.json"

            test_config = {
                "destinations": [
                    {"name": "Feed", "channels": [{"id": "@test", "keywords": {}}]}
                ]
            }

            with open(custom_path, 'w') as f:
                json.dump(test_config, f)

            channel_ids, _ = _load_existing_config(config_dir, "custom_config.json")

            self.assertEqual(channel_ids, {"@test"})


class TestCalculateDiff(unittest.TestCase):
    """Test _calculate_diff() function."""

    def test_identifies_new_channels(self):
        """
        Given: Discovered channels not in existing config
        When: _calculate_diff() called
        Then: Returns new channels in new_channels list
        """
        discovered = [
            {"name": "New Channel 1", "type": "Channel", "info": {"id": "@new1"}},
            {"name": "New Channel 2", "type": "Channel", "info": {"id": "@new2"}},
            {"name": "Existing Channel", "type": "Channel", "info": {"id": "@existing"}},
        ]
        existing_ids = {"@existing"}

        new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

        self.assertEqual(len(new_channels), 2)
        self.assertEqual(new_channels[0]["info"]["id"], "@new1")
        self.assertEqual(new_channels[1]["info"]["id"], "@new2")

    def test_identifies_removed_channels(self):
        """
        Given: Existing config with channels not in discovered list
        When: _calculate_diff() called
        Then: Returns removed channel IDs in removed set
        """
        discovered = [
            {"name": "Channel 1", "type": "Channel", "info": {"id": "@channel1"}},
        ]
        existing_ids = {"@channel1", "@removed1", "@removed2"}

        new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

        self.assertEqual(removed_ids, {"@removed1", "@removed2"})

    def test_no_changes_returns_empty_results(self):
        """
        Given: Discovered channels exactly match existing config
        When: _calculate_diff() called
        Then: Returns empty new_channels and empty removed set
        """
        discovered = [
            {"name": "Channel 1", "type": "Channel", "info": {"id": "@ch1"}},
            {"name": "Channel 2", "type": "Channel", "info": {"id": "@ch2"}},
        ]
        existing_ids = {"@ch1", "@ch2"}

        new_channels, removed_ids = _calculate_diff(discovered, existing_ids)

        self.assertEqual(len(new_channels), 0)
        self.assertEqual(len(removed_ids), 0)


class TestPrintDiffOutput(unittest.TestCase):
    """Test _print_diff_output() function."""

    def test_returns_false_when_no_changes(self):
        """
        Given: No new or removed channels
        When: _print_diff_output() called
        Then: Returns False and logs "NO CHANGES DETECTED"
        """
        new_channels = []
        removed_ids = set()
        existing_ids = {"@ch1", "@ch2"}
        all_channels = [
            {"name": "Ch1", "type": "Channel", "info": {"id": "@ch1"}},
            {"name": "Ch2", "type": "Channel", "info": {"id": "@ch2"}},
        ]

        with self.assertLogs(level='INFO') as log_context:
            result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

        self.assertFalse(result)
        self.assertTrue(any("NO CHANGES DETECTED" in msg for msg in log_context.output))

    def test_returns_true_when_new_channels_exist(self):
        """
        Given: New channels discovered
        When: _print_diff_output() called
        Then: Returns True and logs new channels
        """
        new_channels = [
            {"name": "New Channel", "type": "Channel", "info": {"id": "@new"}}
        ]
        removed_ids = set()
        existing_ids = {"@old"}
        all_channels = new_channels + [{"name": "Old", "type": "Channel", "info": {"id": "@old"}}]

        with self.assertLogs(level='INFO') as log_context:
            result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

        self.assertTrue(result)
        self.assertTrue(any("New Channels" in msg for msg in log_context.output))

    def test_returns_true_when_removed_channels_exist(self):
        """
        Given: Removed/inaccessible channels
        When: _print_diff_output() called
        Then: Returns True and logs removed channels
        """
        new_channels = []
        removed_ids = {"@removed1", "@removed2"}
        existing_ids = {"@removed1", "@removed2", "@still_here"}
        all_channels = [{"name": "Still Here", "type": "Channel", "info": {"id": "@still_here"}}]

        with self.assertLogs(level='INFO') as log_context:
            result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

        self.assertTrue(result)
        self.assertTrue(any("Removed/Inaccessible" in msg for msg in log_context.output))

    def test_prints_summary_with_counts(self):
        """
        Given: Mix of new and removed channels
        When: _print_diff_output() called
        Then: Logs summary with correct counts
        """
        new_channels = [
            {"name": "New1", "type": "Channel", "info": {"id": "@new1"}},
            {"name": "New2", "type": "Supergroup", "info": {"id": "@new2"}},
        ]
        removed_ids = {"@removed"}
        existing_ids = {"@existing", "@removed"}
        all_channels = new_channels + [{"name": "Existing", "type": "Channel", "info": {"id": "@existing"}}]

        with self.assertLogs(level='INFO') as log_context:
            result = _print_diff_output(new_channels, removed_ids, existing_ids, all_channels)

        self.assertTrue(result)
        # Check summary contains expected information
        log_output = '\n'.join(log_context.output)
        self.assertIn("SUMMARY", log_output)
        self.assertIn("New (+)", log_output)  # Don't check exact spacing
        self.assertIn("2", log_output)  # Check count appears somewhere
        self.assertIn("Removed (-)", log_output)
        self.assertIn("1", log_output)


class TestSaveDiscoveredConfig(unittest.TestCase):
    """Test _save_discovered_config() function."""

    def test_saves_config_to_json_file(self):
        """
        Given: List of discovered channels
        When: _save_discovered_config() called
        Then: Saves config_discovered.json with correct structure
        """
        channels = [
            {
                "name": "Channel 1",
                "type": "Channel",
                "info": {"id": "@channel1", "keywords": {}, "ocr": False}
            },
            {
                "name": "Channel 2",
                "type": "Supergroup",
                "info": {"id": "-1001234", "keywords": {}, "ocr": False}
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            with self.assertLogs(level='INFO') as log_context:
                _save_discovered_config(channels, config_dir)

            # Verify file created
            config_path = config_dir / "config_discovered.json"
            self.assertTrue(config_path.exists())

            # Verify content structure
            with open(config_path, 'r') as f:
                saved_config = json.load(f)

            self.assertIn("destinations", saved_config)
            self.assertEqual(len(saved_config["destinations"]), 1)
            self.assertEqual(saved_config["destinations"][0]["name"], "Auto-Generated Feed")
            self.assertEqual(saved_config["destinations"][0]["type"], "discord")
            self.assertEqual(len(saved_config["destinations"][0]["channels"]), 2)

            # Verify channels are just the info dicts
            self.assertEqual(saved_config["destinations"][0]["channels"][0]["id"], "@channel1")
            self.assertEqual(saved_config["destinations"][0]["channels"][1]["id"], "-1001234")

            # Verify log message
            self.assertTrue(any("Configuration saved" in msg for msg in log_context.output))


class TestDiscoverChannels(unittest.TestCase):
    """Test discover_channels() async function - integration tests."""

    def test_discover_channels_basic_mode(self):
        """
        Given: Connected Telegram client with accessible dialogs
        When: discover_channels() called without flags
        Then: Lists all channels and shows type summary

        Note: This is a synchronous test that runs the async function using asyncio.run
        """
        # We need to patch at the point of import inside the function
        with patch('ConfigManager.ConfigManager') as MockConfigManager, \
             patch('telethon.TelegramClient') as MockTelegramClient:

            # Mock ConfigManager
            mock_config = MockConfigManager.return_value
            mock_config.config_dir = Path("/tmp/test_config")
            mock_config.api_id = "12345"
            mock_config.api_hash = "test_hash"

            # Mock TelegramClient
            mock_client = AsyncMock()
            MockTelegramClient.return_value = mock_client

            # Mock dialogs
            mock_dialog1 = Mock()
            mock_dialog1.id = 123
            mock_dialog1.entity = Mock()
            mock_dialog1.entity.username = "test_channel"
            mock_dialog1.entity.title = "Test Channel"
            mock_dialog1.entity.broadcast = True
            mock_dialog1.entity.megagroup = False

            from telethon.tl.types import Channel
            mock_dialog1.entity.__class__ = Channel

            mock_client.get_dialogs.return_value = [mock_dialog1]

            # When: Discover channels
            with self.assertLogs(level='INFO') as log_context:
                asyncio.run(discover_channels(diff_mode=False, generate_config=False))

            # Then: Client started and disconnected
            mock_client.start.assert_called_once()
            mock_client.disconnect.assert_called_once()

            # Verify logging
            log_output = '\n'.join(log_context.output)
            self.assertIn("Found: Test Channel", log_output)
            self.assertIn("Found 1 total dialogs", log_output)


if __name__ == '__main__':
    unittest.main()
