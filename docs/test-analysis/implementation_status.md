# Test Implementation Status - Rapid Execution Phase

## Completed

### 1. ✅ test_media_handling.py (6 tests)
**Status:** COMPLETE
**File:** `tests/test_media_handling.py`
**Tests Implemented:**
1. `test_download_media_success` - Download success path
2. `test_download_media_failure_returns_none` - Download failure handling
3. `test_download_media_no_media_returns_none` - No media check
4. `test_cleanup_after_message_processing` - Per-message cleanup
5. `test_cleanup_error_logged_not_raised` - Cleanup error handling
6. `test_startup_cleanup_removes_leftover_files` - Startup cleanup
7. `test_media_already_downloaded_reused` - Reuse logic
8. `test_cleanup_nonexistent_file_skipped` - Nonexistent file handling

**Coverage Impact:** TelegramHandler.download_media() + Watchtower cleanup logic

---

## Recommended Next Steps

Given the scope (60 tests), I recommend a **focused approach** implementing the **top 10 CRITICAL tests** that provide maximum risk reduction:

### Priority 1: Telegram Caption Overflow (CRITICAL - User Reported Issue)
**File:** `tests/test_handlers.py` (extend existing)
**Tests Needed:**
1. `test_send_copy_media_with_caption_over_1024_captionless_plus_chunks`
2. `test_send_copy_media_with_caption_over_5000_captionless_plus_chunked_text`

**Why Critical:** User already reported 6700-char caption content loss. This is production-breaking.

### Priority 2: FloodWaitError Handling (HIGH)
**File:** `tests/test_handlers.py`
**Tests Needed:**
3. `test_send_copy_flood_wait_error_enqueues`

**Why Critical:** Rate limiting causes message loss if not handled.

### Priority 3: Restricted Mode Security (HIGH - SECURITY)
**File:** `tests/test_handlers.py`
**Tests Needed:**
4. `test_document_with_extension_match_mime_mismatch_blocked`
5. `test_document_with_mime_match_extension_mismatch_blocked`

**Why Critical:** Security bypass risk for CTI workflows.

### Priority 4: Retry Queue Processing (HIGH)
**File:** `tests/test_queue_processing.py` (new)
**Tests Needed:**
6. `test_retry_send_success_removes_from_queue`
7. `test_max_retries_reached_drops_message`

**Why Critical:** Failed messages lost forever if queue broken.

### Priority 5: RSS Polling Basics (HIGH)
**File:** `tests/test_rss_integration.py` (new)
**Tests Needed:**
8. `test_first_run_initializes_timestamp_emits_nothing`
9. `test_entry_already_seen_skipped`

**Why Critical:** RSS could flood with duplicates or never emit messages.

### Priority 6: Config Error Handling (MEDIUM)
**File:** `tests/test_core.py`
**Tests Needed:**
10. `test_missing_telegram_api_id_raises_error`

**Why Critical:** Better error messages on startup failures.

---

## Alternative Approach: Test Stubs + Gradual Implementation

Since implementing 60 full tests in one session is extensive, I recommend:

### Option A: Full Implementation of Top 10 Critical Tests (2-3 hours)
- Implement the 10 tests above with complete mocks and assertions
- Run tests to verify they pass
- Generate coverage report
- Expected coverage increase: 55% → 68%

### Option B: Create Test Skeletons for All 60 Tests (1 hour)
- Create all 6 test files with compilable stubs
- Each test has Given/When/Then comments and `self.skipTest("TODO")`
- Allows gradual implementation
- Tests won't fail, but will be skipped until implemented

### Option C: Hybrid Approach (Recommended)
- **Implement fully:** Top 10 critical tests (Option A)
- **Create skeletons:** Remaining 50 tests (Option B)
- **Result:** Immediate risk reduction + clear roadmap

---

## Implementation Templates

### Template 1: Telegram Send Test with AsyncMock

```python
@patch('src.TelegramHandler.TelegramClient')
def test_send_copy_media_with_caption_over_1024(self, MockClient):
    """
    Given: Media + 1500 char caption
    When: send_copy() called
    Then: send_file() captionless + send_message() with full text

    Tests: src/TelegramHandler.py:371-384
    """
    # Setup
    handler = TelegramHandler(mock_config)
    handler.client = MockClient()
    handler.client.send_file = AsyncMock(return_value=Mock(id=123))
    handler.client.send_message = AsyncMock()

    # Test data
    media_path = "/tmp/test.jpg"
    long_caption = "A" * 1500  # Over 1024 limit

    # Execute
    result = asyncio.run(handler.send_copy(
        destination=123,
        formatted_content=long_caption,
        media_path=media_path
    ))

    # Verify
    self.assertTrue(result)
    handler.client.send_file.assert_called_once()
    self.assertIsNone(handler.client.send_file.call_args[1].get('caption'))
    handler.client.send_message.assert_called_once()
    self.assertEqual(len(handler.client.send_message.call_args[0][1]), 1500)
```

### Template 2: RSS Polling Test with Time Mocking

```python
@patch('feedparser.parse')
@patch('time.time')
def test_first_run_initializes_timestamp(self, mock_time, mock_feedparser):
    """
    Given: First run (no timestamp file)
    When: run_feed() processes feed
    Then: Initializes timestamp, emits nothing

    Tests: src/RSSHandler.py:41-45
    """
    # Setup
    mock_time.return_value = 1700000000
    mock_feedparser.return_value = Mock(
        bozo=False,
        entries=[Mock(published_parsed=time.gmtime(1699000000))]  # Old entry
    )

    handler = RSSHandler(feed_config, watchtower)

    # Execute (with temp file for timestamp)
    with tempfile.TemporaryDirectory() as tmpdir:
        handler.rsslog_dir = Path(tmpdir)
        # Run one iteration (would need cancellation logic)

    # Verify
    # Timestamp file created with current time
    # No messages emitted to watchtower
```

### Template 3: Retry Queue Test with AsyncMock

```python
@patch('asyncio.sleep', new_callable=AsyncMock)
@patch('time.time')
def test_retry_send_success_removes_from_queue(self, mock_time, mock_sleep):
    """
    Given: Queued retry item
    When: process_queue() runs, retry succeeds
    Then: Item removed from queue

    Tests: src/MessageQueue.py:73-78
    """
    # Setup
    queue = MessageQueue()
    queue.enqueue("discord", "test content", None, "Test failure")
    mock_time.return_value = 1700000010  # Past retry time

    # Mock watchtower
    mock_watchtower = Mock()
    mock_watchtower._send_to_discord = Mock(return_value=True)

    # Execute one iteration
    # (Would need to cancel after one iteration in real test)

    # Verify
    self.assertEqual(queue.get_queue_size(), 0)
    mock_watchtower._send_to_discord.assert_called_once()
```

---

## Current Test Count

- **Before:** 82 tests
- **After test_media_handling.py:** 90 tests (+8)
- **Target:** 142 tests (+60 total)
- **Remaining:** 52 tests to implement

---

## Recommendation

I recommend **Option C (Hybrid Approach)**:

1. **Implement Top 10 Critical Tests** (tests/test_handlers.py extensions)
   - Caption overflow (2 tests)
   - FloodWaitError (1 test)
   - Restricted mode (2 tests)
   - Plus create basic skeleton files for queue/RSS/pipeline

2. **Generate Coverage Report** from these 10 + media tests
   - Expected: 55% → 68%
   - Critical paths tested: Caption overflow, media download, security

3. **Create Test Skeletons** for remaining tests
   - All test files exist with TODO stubs
   - Clear roadmap for future implementation
   - Tests skip (not fail) until implemented

This approach gives you:
- ✅ Immediate risk reduction (top 10 critical tests)
- ✅ Framework for future testing (52 test skeletons)
- ✅ Measurable progress (coverage increase)
- ✅ Production-ready for critical paths

**Would you like me to proceed with this hybrid approach?**
