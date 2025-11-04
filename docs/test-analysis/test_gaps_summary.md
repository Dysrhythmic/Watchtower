# WATCHTOWER TEST GAPS - QUICK REFERENCE

**Date:** 2025-11-04
**Overall Confidence:** Medium (65%)
**Estimated Coverage:** 55%

---

## EXECUTIVE SUMMARY

The Watchtower test suite has **82 tests** with good coverage of core utilities (85-100%) but **critical gaps in async operations, RSS polling, retry queue, and Telegram send operations** (0-40% coverage). To achieve production readiness (90% confidence), **~75 new tests needed** across 3 phases over **4-6 weeks**.

---

## TOP 10 CRITICAL GAPS

| # | Gap | Risk | Impact | Likelihood | Test File | Priority |
|---|-----|------|--------|------------|-----------|----------|
| **1** | **Async Message Pipeline** (Watchtower.\_handle\_message) | CRITICAL | Messages lost/misrouted | High | test_integration_pipeline.py (NEW) | P1 |
| **2** | **RSS Feed Polling** (RSSHandler.run\_feed) | CRITICAL | RSS silently fails/floods | Medium | test_rss_integration.py (NEW) | P1 |
| **3** | **Retry Queue Processing** (MessageQueue.process\_queue) | CRITICAL | Failed messages lost forever | Medium | test_queue_processing.py (NEW) | P1 |
| **4** | **Telegram Send Operations** (TelegramHandler.send\_copy) | CRITICAL | Content loss on caption >1024 | High | test_handlers.py (ADD) | P1 |
| **5** | **Media Download** (TelegramHandler.download\_media) | HIGH | OCR/media forwarding broken | Medium | test_media_handling.py (NEW) | P1 |
| **6** | **Restricted Mode Documents** (\_is\_media\_restricted) | HIGH | Security bypass risk | Low | test_handlers.py (ADD) | P2 |
| **7** | **OCR Integration** (is\_ocr\_enabled\_for\_channel trigger) | MEDIUM | OCR feature broken | Low | test_integration_pipeline.py | P1 |
| **8** | **Reply Context** (\_get\_reply\_context) | MEDIUM | Missing reply information | Medium | test_handlers.py (ADD) | P3 |
| **9** | **Config Error Handling** (missing env vars, invalid JSON) | MEDIUM | Startup failures | Medium | test_core.py (ADD) | P2 |
| **10** | **FloodWaitError Handling** (Telegram rate limiting) | MEDIUM | Messages not retried | Medium | test_handlers.py (ADD) | P2 |

---

## QUICK-WIN IMPROVEMENTS

These tests provide high value with low effort:

1. **Restricted Mode Complete Validation** (5 tests, 2 hours)
   - Test document extension + MIME validation
   - Security-critical feature
   - File: `tests/test_handlers.py`

2. **Configuration Error Paths** (6 tests, 3 hours)
   - Test missing API credentials → ValueError
   - Test missing config file → ValueError
   - File: `tests/test_core.py`

3. **FloodWaitError Handling** (2 tests, 1 hour)
   - Test FloodWaitError → enqueue
   - Test retry with backoff
   - File: `tests/test_handlers.py`

4. **Reply Context Extraction** (5 tests, 3 hours)
   - Test fetch success/failure
   - Test text truncation
   - File: `tests/test_handlers.py`

**Total Quick Wins: 18 tests, ~9 hours**

---

## PRODUCTION READINESS CHECKLIST

Before deploying to production, ensure:

### Phase 1: Critical Paths (REQUIRED)
- [ ] Async message pipeline tested (Telegram→Discord, Telegram→Telegram, RSS→Discord, RSS→Telegram)
- [ ] RSS feed polling loop tested (first run, dedup, filtering, errors)
- [ ] Retry queue async processing tested (success, failure, max retries, backoff)
- [ ] Telegram send operations tested (caption overflow, chunking, FloodWaitError)
- [ ] Media download tested (success, failure, cleanup)

### Phase 2: Security & Error Handling (RECOMMENDED)
- [ ] Restricted mode document validation complete
- [ ] Configuration error paths tested (missing files, invalid JSON, missing env vars)
- [ ] Network error handling tested (Discord 429/500, Telegram errors, RSS errors)
- [ ] Top-level exception handling tested

### Phase 3: Completeness (NICE TO HAVE)
- [ ] Reply context extraction tested
- [ ] Optional field formatting tested (OCR, defanged URLs, reply context)
- [ ] Startup/shutdown lifecycle tested
- [ ] Metrics integration tested

---

## COVERAGE BY MODULE

| Module | LOC | Current Coverage | Test Count | Target Coverage | Gap |
|--------|-----|------------------|------------|-----------------|-----|
| **MessageData** | 38 | 100% ✓ | 6 | 100% | None |
| **MetricsCollector** | 106 | 95% ✓ | 13 | 95% | reset_metric |
| **OCRHandler** | 55 | 95% ✓ | 6 | 95% | Integration trigger |
| **DestinationHandler** | 123 | 90% ✓ | 9 | 90% | None |
| **MessageRouter** | 197 | 85% ✓ | 11 | 90% | is_*_restricted/enabled |
| **DiscordHandler** | 141 | 75% ⚠ | 10 | 85% | Reply/OCR/URL formatting |
| **MessageQueue** | 150 | 60% ⚠ | 9 | 90% | **process_queue, _retry_send** |
| **TelegramHandler** | 474 | 40% ❌ | 14 | 90% | **send_copy, download_media** |
| **ConfigManager** | 302 | 30% ❌ | 2 | 80% | Error paths, RSS dedup |
| **RSSHandler** | 189 | 30% ❌ | 8 | 90% | **run_feed, _process_entry** |
| **Watchtower** | 739 | 20% ❌ | 2 | 85% | **Entire async pipeline** |

**Legend:** ✓ Good (≥85%) | ⚠ Needs Work (50-84%) | ❌ Critical Gap (<50%)

---

## ROADMAP TO 90% CONFIDENCE

### Phase 1: Critical Paths (2-3 weeks, 40 tests)
**Goal:** Eliminate all CRITICAL gaps

**New Test Files:**
- `test_integration_pipeline.py` (7 tests) - Async message pipeline
- `test_rss_integration.py` (7 tests) - RSS polling
- `test_queue_processing.py` (6 tests) - Retry queue
- `test_media_handling.py` (6 tests) - Media download

**Updated Files:**
- `test_handlers.py` (+8 tests) - Telegram send operations

**Expected Coverage After:** 75%

---

### Phase 2: Security & Error Handling (1-2 weeks, 23 tests)
**Goal:** Close security gaps and error handling

**Updated Files:**
- `test_handlers.py` (+5 tests) - Restricted mode complete
- `test_core.py` (+6 tests) - Config error handling
- `test_error_handling.py` (+12 tests, NEW) - All error paths

**Expected Coverage After:** 82%

---

### Phase 3: Completeness (1 week, 12 tests)
**Goal:** Fill remaining gaps

**Updated Files:**
- `test_handlers.py` (+5 tests) - Reply context
- `test_integration.py` (+6 tests) - Formatting, startup/shutdown
- `test_core.py` (+1 test) - Metrics

**Expected Coverage After:** 90%

---

## IMPLEMENTATION GUIDE

### Step 1: Set Up Test Infrastructure

```bash
# Ensure test dependencies installed
pip install unittest coverage

# Run existing tests to verify baseline
python -m unittest discover -v tests/

# Generate coverage baseline
coverage run -m unittest discover tests/
coverage report
coverage html
```

### Step 2: Create New Test Files

Copy stubs from `docs/test_stubs_proposal.py` to appropriate test files:

```bash
# Create new test files
touch tests/test_integration_pipeline.py
touch tests/test_rss_integration.py
touch tests/test_queue_processing.py
touch tests/test_media_handling.py
touch tests/test_error_handling.py
```

### Step 3: Implement Tests by Priority

**Week 1-2:** Async pipeline + RSS polling (Priority 1.1, 1.2)
- Focus on `test_integration_pipeline.py` and `test_rss_integration.py`
- Mock Telegram API, Discord webhooks, feedparser
- Verify end-to-end flows

**Week 2-3:** Retry queue + Telegram send (Priority 1.3, 1.4)
- Focus on `test_queue_processing.py` and `test_handlers.py`
- Mock async operations with AsyncMock
- Test caption overflow (CRITICAL)

**Week 3:** Media download (Priority 1.5)
- Focus on `test_media_handling.py`
- Mock file operations
- Test cleanup logic

**Week 4:** Security + error handling (Priority 2)
- Complete restricted mode tests
- Add config error tests
- Add network error tests

**Week 5-6:** Polish + completeness (Priority 3)
- Reply context tests
- Formatting tests
- Integration tests

### Step 4: Verify Coverage

```bash
# Run new tests
python -m unittest discover -v tests/

# Check coverage improvement
coverage run -m unittest discover tests/
coverage report --show-missing
coverage html

# Review HTML report
open htmlcov/index.html
```

### Step 5: Optional - Mutation Testing

```bash
# Install mutmut
pip install mutmut

# Run mutation testing on critical modules
mutmut run --paths-to-mutate=src/Watchtower.py,src/RSSHandler.py,src/TelegramHandler.py

# Check results
mutmut results
mutmut html
```

---

## EXAMPLE: IMPLEMENTING A CRITICAL TEST

Here's how to implement the **caption overflow test** (CRITICAL gap #4):

### 1. Copy Stub from test_stubs_proposal.py

```python
@patch('telethon.TelegramClient')
def test_send_copy_media_with_caption_over_1024_captionless_plus_chunks(self, MockClient):
    # Given: Media + 1500 char caption
    # When: send_copy() called
    # Then: send_file() captionless + send_message() with full text
    self.fail("TODO: Implement test")
```

### 2. Implement Test

```python
@patch('telethon.TelegramClient')
async def test_send_copy_media_with_caption_over_1024_captionless_plus_chunks(self, MockClient):
    # Given: Media + 1500 char caption
    handler = TelegramHandler(channel_id=123, channel_name="test")
    handler.client = MockClient()
    handler.client.send_file = AsyncMock()
    handler.client.send_message = AsyncMock()

    media_path = "/tmp/test.jpg"
    long_caption = "A" * 1500  # Over 1024 limit

    # When: send_copy() called
    result = await handler.send_copy(
        destination=123,
        formatted_content=long_caption,
        media_path=media_path
    )

    # Then: send_file() captionless + send_message() with full text
    self.assertTrue(result)

    # Assert send_file called with NO caption
    handler.client.send_file.assert_called_once()
    call_args = handler.client.send_file.call_args
    self.assertIsNone(call_args[1].get('caption'))

    # Assert send_message called with full 1500 char text
    handler.client.send_message.assert_called_once()
    message_text = handler.client.send_message.call_args[0][1]
    self.assertEqual(len(message_text), 1500)
    self.assertEqual(message_text, long_caption)
```

### 3. Run Test

```bash
python -m unittest tests.test_handlers.TestTelegramSendOperations.test_send_copy_media_with_caption_over_1024_captionless_plus_chunks -v
```

### 4. Verify Coverage

```bash
coverage run -m unittest tests.test_handlers.TestTelegramSendOperations.test_send_copy_media_with_caption_over_1024_captionless_plus_chunks
coverage report --include=src/TelegramHandler.py
```

---

## HELPFUL COMMANDS

```bash
# Run all tests
python -m unittest discover -v tests/

# Run specific test file
python -m unittest tests.test_handlers -v

# Run specific test class
python -m unittest tests.test_handlers.TestTelegramSendOperations -v

# Run specific test method
python -m unittest tests.test_handlers.TestTelegramSendOperations.test_send_copy_media_with_caption_over_1024_captionless_plus_chunks -v

# Generate coverage report
coverage run -m unittest discover tests/
coverage report --show-missing

# Generate HTML coverage report
coverage html
open htmlcov/index.html

# Check coverage for specific module
coverage report --include=src/TelegramHandler.py
```

---

## RESOURCES

- **Full Report:** [test_coverage_analysis.md](test_coverage_analysis.md)
- **Traceability JSON:** [test_audit_traceability.json](test_audit_traceability.json)
- **Coverage Summary JSON:** [test_audit_coverage_summary.json](test_audit_coverage_summary.json)
- **Test Stubs:** [test_stubs_proposal.py](test_stubs_proposal.py)
- **Existing Tests:**
  - [tests/test_core.py](../tests/test_core.py) - 43 tests
  - [tests/test_handlers.py](../tests/test_handlers.py) - 26 tests
  - [tests/test_integration.py](../tests/test_integration.py) - 13 tests

---

## QUESTIONS?

For detailed analysis of any feature or gap, see:
- **Feature inventory:** test_coverage_analysis.md Part 3
- **Test coverage mapping:** test_coverage_analysis.md Part 4
- **Edge cases:** test_coverage_analysis.md Part 8
- **Error handling:** test_coverage_analysis.md Part 9
- **Recommendations:** test_coverage_analysis.md Part 10

**Contact:** See project README for maintainer information
