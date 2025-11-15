"""E2E tests for attachment handling through send → fail → enqueue → retry cycle."""
import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from MessageData import MessageData
from AppTypes import APP_TYPE_TELEGRAM, APP_TYPE_DISCORD
from SendStatus import SendStatus
from conftest import create_mock_config


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_discord_send_failure_enqueues_with_correct_attachment_path(mock_post, mock_config_class, mock_telegram_client):
    """Test Discord send failure enqueues message with correct attachment_path."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_response_429.json.return_value = {'retry_after': 5.0}
    mock_post.return_value = mock_response_429

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')
    assert os.path.exists(test_image), "test-img.jpg must exist for this test"

    msg = MessageData(
        source_type=APP_TYPE_TELEGRAM,
        channel_name='test',
        text='Test message with image',
        attachment_path=test_image
    )

    destination = {
        'name': 'TestDiscord',
        'type': APP_TYPE_DISCORD,
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    result = asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

    assert result == SendStatus.QUEUED
    assert app.message_queue.get_queue_size() == 1

    queued_item = app.message_queue._queue[0]
    assert queued_item.attachment_path == test_image
    assert queued_item.attachment_path is not None


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_discord_attachment_survives_retry_cycle(mock_config_class, mock_telegram_client):
    """Test attachment is correctly passed through enqueue → retry → resend cycle."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    destination = {
        'name': 'TestDiscord',
        'type': APP_TYPE_DISCORD,
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    app.message_queue.enqueue(
        destination=destination,
        formatted_content="Test retry with image",
        attachment_path=test_image,
        reason="test"
    )

    app.discord.send_message = AsyncMock(return_value=True)

    retry_item = app.message_queue._queue[0]
    success = asyncio.run(app.message_queue._retry_send(retry_item, app))

    assert success

    app.discord.send_message.assert_called_once()
    call_args = app.discord.send_message.call_args

    assert call_args[0][2] == test_image


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_discord_attachment_with_no_media_path_parameter(mock_post, mock_config_class, mock_telegram_client):
    """Test that enqueue() rejects media_path parameter."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    destination = {
        'name': 'TestDiscord',
        'type': APP_TYPE_DISCORD,
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    with pytest.raises(TypeError) as context:
        app.message_queue.enqueue(
            destination=destination,
            formatted_content="Test",
            media_path='/path/to/image.jpg',
            reason="test"
        )

    assert 'media_path' in str(context.value)


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_telegram_send_failure_enqueues_with_correct_attachment_path(mock_config_class, mock_telegram_client):
    """Test Telegram send failure enqueues message with correct attachment_path."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    mock_client_instance = AsyncMock()
    mock_telegram_client.return_value = mock_client_instance

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    app.telegram.send_message = AsyncMock(return_value=False)

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')
    assert os.path.exists(test_image), "test-img.jpg must exist for this test"

    msg = MessageData(
        source_type=APP_TYPE_TELEGRAM,
        channel_name='test',
        text='Test message with image',
        attachment_path=test_image
    )

    destination = {
        'name': 'TestTelegram',
        'type': APP_TYPE_TELEGRAM,
        'telegram_dst_channel': '-1001234567890'
    }

    result = asyncio.run(app._send_to_telegram(msg, destination, msg.text, True))

    assert result == SendStatus.QUEUED
    assert app.message_queue.get_queue_size() == 1

    queued_item = app.message_queue._queue[0]
    assert queued_item.attachment_path == test_image
    assert queued_item.attachment_path is not None


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_telegram_attachment_survives_retry_cycle(mock_config_class, mock_telegram_client):
    """Test attachment is correctly passed through enqueue → retry → resend cycle."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    mock_client_instance = AsyncMock()
    mock_telegram_client.return_value = mock_client_instance

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    destination = {
        'name': 'TestTelegram',
        'type': APP_TYPE_TELEGRAM,
        'telegram_dst_channel': '-1001234567890',
        'telegram_dst_id': -1001234567890
    }

    app.message_queue.enqueue(
        destination=destination,
        formatted_content="Test retry with image",
        attachment_path=test_image,
        reason="test"
    )

    app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    app.telegram.send_message = AsyncMock(return_value=True)

    retry_item = app.message_queue._queue[0]
    success = asyncio.run(app.message_queue._retry_send(retry_item, app))

    assert success

    app.telegram.send_message.assert_called_once()
    call_args = app.telegram.send_message.call_args

    assert call_args[0][2] == test_image


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_ocr_extraction_with_attachment_through_retry(mock_post, mock_config_class, mock_telegram_client):
    """Test message with OCR data and attachment can be enqueued."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_response_429.json.return_value = {'retry_after': 5.0}
    mock_post.return_value = mock_response_429

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    msg = MessageData(
        source_type=APP_TYPE_TELEGRAM,
        channel_name='test',
        text='Original message',
        attachment_path=test_image,
        ocr_raw='Extracted text from image'
    )

    destination = {
        'name': 'TestDiscord',
        'type': APP_TYPE_DISCORD,
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    result = asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

    assert result == SendStatus.QUEUED
    assert app.message_queue.get_queue_size() == 1

    queued_item = app.message_queue._queue[0]
    assert queued_item.formatted_content is not None
    assert queued_item.attachment_path == test_image


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_telegram_caption_length_handling_with_retry(mock_config_class, mock_telegram_client):
    """Test long captions are properly chunked when retried."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    mock_client_instance = AsyncMock()
    mock_telegram_client.return_value = mock_client_instance

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    long_content = "A" * 1500

    destination = {
        'name': 'TestTelegram',
        'type': APP_TYPE_TELEGRAM,
        'telegram_dst_channel': '-1001234567890',
        'telegram_dst_id': -1001234567890
    }

    app.message_queue.enqueue(
        destination=destination,
        formatted_content=long_content,
        attachment_path=test_image,
        reason="test"
    )

    app.telegram.resolve_destination = AsyncMock(return_value=-1001234567890)
    app.telegram.send_message = AsyncMock(return_value=True)

    retry_item = app.message_queue._queue[0]
    success = asyncio.run(app.message_queue._retry_send(retry_item, app))

    assert success

    app.telegram.send_message.assert_called_once()


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
@patch('requests.post')
def test_watchtower_discord_failure_calls_enqueue_with_attachment_path(mock_post, mock_config_class, mock_telegram_client):
    """Verify enqueue called with attachment_path, not media_path."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    original_enqueue = app.message_queue.enqueue
    app.message_queue.enqueue = Mock(side_effect=original_enqueue)

    mock_response_429 = Mock()
    mock_response_429.status_code = 429
    mock_response_429.json.return_value = {'retry_after': 5.0}
    mock_post.return_value = mock_response_429

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    msg = MessageData(
        source_type=APP_TYPE_TELEGRAM,
        channel_name='test',
        text='Test',
        attachment_path=test_image
    )

    destination = {
        'name': 'TestDiscord',
        'type': APP_TYPE_DISCORD,
        'discord_webhook_url': 'https://discord.com/webhook'
    }

    asyncio.run(app._send_to_discord(msg, destination, msg.text, True))

    app.message_queue.enqueue.assert_called_once()

    call_kwargs = app.message_queue.enqueue.call_args.kwargs
    assert 'attachment_path' in call_kwargs
    assert 'media_path' not in call_kwargs
    assert call_kwargs['attachment_path'] == test_image


@patch('TelegramHandler.TelegramClient')
@patch('ConfigManager.ConfigManager')
def test_watchtower_telegram_failure_calls_enqueue_with_attachment_path(mock_config_class, mock_telegram_client):
    """Verify enqueue called with attachment_path, not media_path."""
    from Watchtower import Watchtower

    mock_config = create_mock_config()
    mock_config_class.return_value = mock_config

    mock_client_instance = AsyncMock()
    mock_telegram_client.return_value = mock_client_instance

    app = Watchtower(sources=[APP_TYPE_TELEGRAM])

    original_enqueue = app.message_queue.enqueue
    app.message_queue.enqueue = Mock(side_effect=original_enqueue)

    app.telegram.send_message = AsyncMock(return_value=False)

    test_image = os.path.join(os.path.dirname(__file__), 'test-img.jpg')

    msg = MessageData(
        source_type=APP_TYPE_TELEGRAM,
        channel_name='test',
        text='Test',
        attachment_path=test_image
    )

    destination = {
        'name': 'TestTelegram',
        'type': APP_TYPE_TELEGRAM,
        'telegram_dst_channel': '-1001234567890'
    }

    asyncio.run(app._send_to_telegram(msg, destination, msg.text, True))

    app.message_queue.enqueue.assert_called_once()

    call_kwargs = app.message_queue.enqueue.call_args.kwargs
    assert 'attachment_path' in call_kwargs
    assert 'media_path' not in call_kwargs
    assert call_kwargs['attachment_path'] == test_image
