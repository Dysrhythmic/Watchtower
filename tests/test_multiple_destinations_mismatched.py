import unittest
import sys
import os
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone
from pathlib import Path
import asyncio

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from Watchtower import Watchtower
from MessageData import MessageData


class TestMultipleDestinationsMismatchedConfigs(unittest.TestCase):
    """
    Test multiple destinations with different configurations.

    Ensures that when a single message routes to multiple destinations,
    each destination's specific config (OCR, restricted_mode, parser) is
    applied independently without affecting others.
    """

    def test_ocr_enabled_for_some_destinations_not_others(self):
        """
        Test that OCR is processed for destinations that need it, but not for others.

        Scenario: Same Telegram channel routes to 2 destinations:
        - Destination A: OCR enabled
        - Destination B: OCR disabled

        Expected: OCR should be extracted once and used only for Destination A.
        """
        # Create mock config with two destinations, one with OCR
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        mock_config.webhooks = [
            {
                'name': 'Dest A (OCR enabled)',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook_a',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': True  # OCR enabled
                }]
            },
            {
                'name': 'Dest B (OCR disabled)',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook_b',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,
                    'parser': None,
                    'ocr': False  # OCR disabled
                }]
            }
        ]

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)

        mock_router = Mock()
        mock_router.get_destinations = Mock(return_value=[
            {'name': 'Dest A', 'type': 'discord', 'webhook_url': 'url_a', 'parser': None,
             'restricted_mode': False, 'ocr': True, 'keywords': []},
            {'name': 'Dest B', 'type': 'discord', 'webhook_url': 'url_b', 'parser': None,
             'restricted_mode': False, 'ocr': False, 'keywords': []}
        ])
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=True)  # At least one dest has OCR
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=True)
        mock_ocr.extract_text = Mock(return_value="OCR extracted text")

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text or "")

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
        app = Watchtower(
            sources=['telegram'],
            config=mock_config,
            telegram=mock_telegram,
            discord=mock_discord,
            router=mock_router,
            ocr=mock_ocr,
            message_queue=mock_queue,
            metrics=mock_metrics
        )

        # Create message with media
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Regular text",
            has_media=True,
            media_type="photo",
            media_path="/tmp/photo.jpg"
        )
        msg.original_message = Mock()

        # Mock os.path.exists so media file is considered to exist
        with patch('os.path.exists', return_value=True):
            # Process message
            asyncio.run(app._handle_message(msg, False))

        # Verify OCR was called exactly once
        mock_ocr.extract_text.assert_called_once()

        # Verify message was sent to both destinations
        self.assertEqual(mock_discord.send_message.call_count, 2,
            "Message should be sent to both destinations")

    def test_restricted_mode_for_some_destinations_not_others(self):
        """
        Test that restricted mode is applied per-destination.

        Scenario: Same channel routes to 2 destinations:
        - Destination A: restricted_mode=True (blocks certain media)
        - Destination B: restricted_mode=False (allows all media)

        Expected: Media should be blocked for Dest A but sent to Dest B.
        """
        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        mock_config.webhooks = [
            {
                'name': 'Dest A (Restricted)',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook_a',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': True,  # Restricted
                    'parser': None,
                    'ocr': False
                }]
            },
            {
                'name': 'Dest B (Open)',
                'type': 'discord',
                'webhook_url': 'https://discord.com/webhook_b',
                'channels': [{
                    'id': '@test_channel',
                    'keywords': [],
                    'restricted_mode': False,  # Not restricted
                    'parser': None,
                    'ocr': False
                }]
            }
        ]

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)
        mock_telegram._is_media_restricted = Mock(return_value=True)  # Media IS restricted
        mock_telegram.download_media = AsyncMock(return_value="/tmp/media.jpg")

        mock_router = Mock()
        mock_router.get_destinations = Mock(return_value=[
            {'name': 'Dest A', 'type': 'discord', 'webhook_url': 'url_a', 'parser': None,
             'restricted_mode': True, 'ocr': False, 'keywords': []},
            {'name': 'Dest B', 'type': 'discord', 'webhook_url': 'url_b', 'parser': None,
             'restricted_mode': False, 'ocr': False, 'keywords': []}
        ])
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)
        mock_router.parse_msg = Mock(side_effect=lambda msg, parser: msg)

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text or "")

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=False)

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
        app = Watchtower(
            sources=['telegram'],
            config=mock_config,
            telegram=mock_telegram,
            discord=mock_discord,
            router=mock_router,
            ocr=mock_ocr,
            message_queue=mock_queue,
            metrics=mock_metrics
        )

        # Create message with restricted media (photo)
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Message with photo",
            has_media=True,
            media_type="photo"
        )
        msg.original_message = Mock()

        # Process message
        asyncio.run(app._handle_message(msg, False))

        # Verify both destinations received the message
        self.assertEqual(mock_discord.send_message.call_count, 2,
            "Message should be sent to both destinations")

        # Check the send_message calls
        calls = mock_discord.send_message.call_args_list

        # First call (Dest A - restricted) should NOT include media
        self.assertIsNone(calls[0][0][2],  # media_path argument
            "Restricted destination should not receive media")

        # Second call (Dest B - not restricted) SHOULD include media
        self.assertIsNotNone(calls[1][0][2],  # media_path argument
            "Non-restricted destination should receive media")

    def test_different_parsers_per_destination(self):
        """
        Test that different parsers are applied per-destination.

        Scenario: Same channel routes to 2 destinations:
        - Destination A: Parser trims first 2 lines
        - Destination B: No parser (original text)

        Expected: Each destination gets appropriately parsed content.
        """
        # Create mock config
        mock_config = Mock()
        mock_config.tmp_dir = Path("/tmp")
        mock_config.attachments_dir = Mock()
        mock_config.attachments_dir.exists.return_value = True
        mock_config.attachments_dir.glob.return_value = []

        # Create mocks
        mock_telegram = Mock()
        mock_telegram.client = Mock()
        mock_telegram.client.is_connected = Mock(return_value=False)

        mock_router = Mock()

        # Create two destination configs with different parsers
        dest_a_parser = {'trim_front_lines': 2, 'trim_back_lines': 0}
        dest_b_parser = None

        mock_router.get_destinations = Mock(return_value=[
            {'name': 'Dest A', 'type': 'discord', 'webhook_url': 'url_a',
             'parser': dest_a_parser, 'restricted_mode': False, 'ocr': False, 'keywords': []},
            {'name': 'Dest B', 'type': 'discord', 'webhook_url': 'url_b',
             'parser': dest_b_parser, 'restricted_mode': False, 'ocr': False, 'keywords': []}
        ])

        # Mock parse_msg to actually apply the parser
        def mock_parse(msg, parser):
            parsed = MessageData(
                source_type=msg.source_type,
                channel_id=msg.channel_id,
                channel_name=msg.channel_name,
                username=msg.username,
                timestamp=msg.timestamp,
                text=msg.text
            )
            if parser and parser.get('trim_front_lines', 0) > 0:
                lines = msg.text.split('\n')
                trimmed = lines[parser['trim_front_lines']:]
                parsed.text = '\n'.join(trimmed)
            return parsed

        mock_router.parse_msg = Mock(side_effect=mock_parse)
        mock_router.is_ocr_enabled_for_channel = Mock(return_value=False)

        mock_discord = Mock()
        mock_discord.send_message = Mock(return_value=True)
        mock_discord.format_message = Mock(side_effect=lambda msg, dest: msg.text)

        mock_ocr = Mock()
        mock_ocr.is_available = Mock(return_value=False)

        mock_queue = Mock()
        mock_queue.get_queue_size = Mock(return_value=0)

        mock_metrics = Mock()

        # Create Watchtower instance
        app = Watchtower(
            sources=['telegram'],
            config=mock_config,
            telegram=mock_telegram,
            discord=mock_discord,
            router=mock_router,
            ocr=mock_ocr,
            message_queue=mock_queue,
            metrics=mock_metrics
        )

        # Create message with multiple lines
        msg = MessageData(
            source_type="telegram",
            channel_id="@test_channel",
            channel_name="Test Channel",
            username="@user",
            timestamp=datetime.now(timezone.utc),
            text="Line 1\nLine 2\nLine 3\nLine 4"
        )

        # Process message
        asyncio.run(app._handle_message(msg, False))

        # Verify parse_msg was called twice with different parsers
        self.assertEqual(mock_router.parse_msg.call_count, 2)

        # Verify different parsers were passed
        call_1_parser = mock_router.parse_msg.call_args_list[0][0][1]
        call_2_parser = mock_router.parse_msg.call_args_list[1][0][1]

        self.assertEqual(call_1_parser, dest_a_parser,
            "First destination should use parser A")
        self.assertIsNone(call_2_parser,
            "Second destination should have no parser")


if __name__ == '__main__':
    unittest.main()
