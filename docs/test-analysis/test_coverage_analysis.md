# WATCHTOWER TEST COVERAGE ANALYSIS
## Comprehensive Assessment of Test Suite Confidence

**Date:** 2025-11-04
**Project Root:** `/mnt/c/Users/jaket/Documents/Code/watchtower`
**Analysis Scope:** All source files in `src/`, all test files in `tests/`, configuration files in `config/`

---

## EXECUTIVE SUMMARY

### Confidence Verdict: **MEDIUM (65%)**

The Watchtower application has a **moderately robust** test suite with **82 test methods** across 3 test files covering core functionality. However, there are **significant gaps** in coverage for critical paths including async operations, retry queue processing, RSS polling, media download, OCR processing flow, error handling, and complex integration scenarios.

**Justification:** While core utilities (routing, keyword matching, message formatting, chunking) are well-tested at 85%+, the critical async message pipeline, RSS polling, retry queue processing, and Telegram send operations have 0-40% coverage. This leaves substantial risk for production failures in key workflows.

### Top 5 Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **1. Async message pipeline failures** (Watchtower._handle_message: 0% tested) | Critical - messages lost/misrouted | High | Add integration tests mocking Telegram/Discord APIs with various message types |
| **2. RSS feeds silently fail** (RSSHandler.run_feed: 0% tested) | High - entire RSS pipeline broken | Medium | Add tests for RSS polling loop with mocked feedparser, timestamp persistence |
| **3. Retry queue never processes** (MessageQueue.process_queue: 0% tested) | Critical - failed messages lost forever | Medium | Add async tests for queue processing with mocked sleep/retry logic |
| **4. Telegram messages truncated/lost** (TelegramHandler.send_copy: 0% tested) | High - content loss on caption overflow | High | Add tests for >1024 caption handling, >4096 message chunking |
| **5. Media download failures unhandled** (TelegramHandler.download_media: 0% tested) | Medium - OCR/media forwarding broken | Medium | Add tests for download success/failure, cleanup logic |

### Key Numbers

| Metric | Value |
|--------|-------|
| **Test Methods** | 82 (test_core: 43, test_handlers: 26, test_integration: 13) |
| **Source Files** | 11 modules |
| **Total Source LOC** | ~2,514 lines |
| **Estimated Overall Coverage** | 55% |
| **Well-Tested Components (>85%)** | MessageData (100%), MetricsCollector (95%), OCRHandler (95%), DestinationHandler (90%), MessageRouter (85%) |
| **Poorly-Tested Components (<40%)** | Watchtower (20%), RSSHandler (30%), ConfigManager (30%), TelegramHandler (40%) |
| **Critical Untested Paths** | 7 (async pipeline, RSS polling, retry queue, Telegram send, media download, OCR integration, reply context) |

---

## PART 1: PROJECT CONTEXT

### Environment Information

```
Project root: /mnt/c/Users/jaket/Documents/Code/watchtower
Platform: Linux 5.15.167.4-microsoft-standard-WSL2 (WSL2)
Python: 3.x (unittest framework)
OS: Linux
```

### Test Execution Commands

**Run all tests:**
```bash
python -m unittest discover -v tests/
```

**Run with coverage (recommended):**
```bash
coverage run -m unittest discover tests/
coverage report
coverage xml
coverage html
```

**Mutation testing (if available):**
```bash
# Not currently configured
# Recommendation: Install mutmut and configure for critical modules
pip install mutmut
mutmut run --paths-to-mutate=src/
```

### Output Directory

All analysis documents are placed in: `docs/`

---

## PART 2: SOURCE CODE INVENTORY

### Python Source Files (11 files in src/)

| File | LOC | Purpose | Complexity | Coverage Est. |
|------|-----|---------|------------|---------------|
| [MessageData.py](../src/MessageData.py) | 38 | Message data container (dataclass) | Low | 100% |
| [OCRHandler.py](../src/OCRHandler.py) | 55 | EasyOCR text extraction from images | Medium | 95% |
| [MetricsCollector.py](../src/MetricsCollector.py) | 106 | JSON-based metrics tracking | Low | 95% |
| [DestinationHandler.py](../src/DestinationHandler.py) | 123 | Abstract base for Discord/Telegram handlers | Medium | 90% |
| [MessageRouter.py](../src/MessageRouter.py) | 197 | Message routing and keyword matching | High | 85% |
| [DiscordHandler.py](../src/DiscordHandler.py) | 141 | Discord webhook sending | Medium | 75% |
| [MessageQueue.py](../src/MessageQueue.py) | 150 | Retry queue with exponential backoff | High | 60% |
| [TelegramHandler.py](../src/TelegramHandler.py) | 474 | Telegram client operations | Very High | 40% |
| [ConfigManager.py](../src/ConfigManager.py) | 302 | Configuration loading and validation | High | 30% |
| [RSSHandler.py](../src/RSSHandler.py) | 189 | RSS feed polling and parsing | High | 30% |
| [Watchtower.py](../src/Watchtower.py) | 739 | Main orchestration and message pipeline | Very High | 20% |

**Total Source LOC:** ~2,514 lines

---

## PART 3: EXHAUSTIVE FEATURE INVENTORY

### Feature 1: Message Routing

**Code Location:** [MessageRouter.py:12-197](../src/MessageRouter.py#L12-L197)

**Core Functions:**
- `get_destinations(message_data)` (lines 41-95): Matches messages to destinations via keywords
- `parse_msg(message_data, parser_config)` (lines 97-161): Trims lines from message text
- `is_channel_restricted(channel_id, channel_name)` (lines 19-26): Checks restricted mode
- `is_ocr_enabled_for_channel(channel_id, channel_name)` (lines 28-35): Checks OCR enablement
- `_channel_matches(channel_id, channel_name, config_id)` (lines 178-196): Channel ID matching logic

**Expectations:**
- Empty keywords → forwards all messages
- Keyword matching is case-insensitive
- OCR text included in searchable text when OCR enabled
- Parser trims specified lines from message text
- Numeric channel IDs match with/without -100 prefix
- RSS URLs match as channel IDs

**Edge Cases:**
- Empty keywords → forwards all (line 88-89) ✓ TESTED
- Keyword matching case-insensitive (line 91) ✓ TESTED
- OCR text in search (lines 82-84) ✓ TESTED
- Parser trims all content → placeholder (lines 135-139) ✗ NOT TESTED
- Negative parser values → logged warning (lines 120-122) ✗ NOT TESTED
- -100 prefix handling (lines 189-194) ✗ NOT TESTED
- RSS URL as channel ID (lines 181-182) ✓ TESTED

**Configuration Knobs:**
- `keywords.files`: Array of keyword file names
- `keywords.inline`: Array of inline keyword strings
- `parser.trim_front_lines`: Integer (lines to remove from start)
- `parser.trim_back_lines`: Integer (lines to remove from end)
- `restricted_mode`: Boolean
- `ocr`: Boolean

**External Dependencies:** ConfigManager for webhook/channel configuration

**Test Coverage:** 85% (11 tests in test_core.py)

---

### Feature 2: Keyword Filtering

**Code Location:** [ConfigManager.py:204-291](../src/ConfigManager.py#L204-L291)

**Core Functions:**
- `_resolve_keywords(keyword_config)` (lines 247-291): Loads keywords from files + inline
- `_load_keyword_file(filename)` (lines 204-245): Loads and caches keyword JSON files

**Expectations:**
- Keywords loaded from JSON files in `config/` directory
- Files cached to prevent redundant reads
- Inline keywords combined with file keywords
- Duplicates automatically deduplicated
- None/null keywords → forward all messages

**Edge Cases:**
- None/null keywords → forward all (line 260-261) ✗ NOT TESTED
- Duplicate keywords deduplicated (line 289) ✗ NOT TESTED
- Missing keyword file → ValueError (line 224) ✗ NOT TESTED
- Invalid JSON → ValueError (line 229-230) ✗ NOT TESTED
- File caching (lines 217-218) ✓ TESTED

**Configuration Format:**
```json
{
  "keywords": {
    "files": ["kw-general.json", "kw-checks.json"],
    "inline": ["CVE", "ransomware"]
  }
}
```

**External Dependencies:** File system (config/*.json files)

**Test Coverage:** 30% (1 test for file+inline combination, missing error paths)

---

### Feature 3: OCR Text Extraction

**Code Location:** [OCRHandler.py:17-55](../src/OCRHandler.py#L17-L55)

**Core Functions:**
- `is_available()` (lines 23-25): Checks if EasyOCR installed
- `extract_text(image_path)` (lines 38-54): Extracts text from image

**Expectations:**
- Returns None if EasyOCR not installed
- Lazy-loads OCR reader on first use
- Extracts English text from images
- Returns None on empty results or errors
- No GPU acceleration (cpu-only)

**Edge Cases:**
- EasyOCR not installed → None (lines 40-42) ✓ TESTED
- Reader init fails → None (lines 35-36) ✓ TESTED
- OCR processing fails → None (lines 52-54) ✓ TESTED
- Empty OCR result → None (line 51) ✓ TESTED
- Lazy reader init (lines 28-36) ✓ TESTED

**Configuration Parameters:**
- Language: English only (`['en']`)
- GPU: Disabled (`gpu=False`)
- Detail: 0 (text only, no bounding boxes)
- Paragraph mode: True
- Contrast threshold: 0.15
- Min size: 10

**External Dependencies:** EasyOCR library (optional), image files

**Test Coverage:** 95% (6 tests in test_handlers.py)

---

### Feature 4: RSS Feed Polling

**Code Location:** [RSSHandler.py:17-189](../src/RSSHandler.py#L17-L189)

**Core Functions:**
- `run_feed(feed)` (lines 132-189): Infinite polling loop for single feed
- `_process_entry(entry, ...)` (lines 102-130): Processes single RSS entry
- `_format_entry_text(entry)` (lines 83-100): Formats RSS entry as message text
- `_strip_html_tags(text)` (lines 69-81): Removes HTML from RSS content
- `_read_last_ts(rss_name)` (lines 38-53): Reads last seen timestamp
- `_write_last_ts(rss_name, timestamp)` (lines 55-58): Writes last seen timestamp

**Expectations:**
- Polls RSS feeds every 5 minutes (configurable)
- Skips entries older than 2 days
- Skips already-seen entries via timestamp tracking
- Formats entries with title + URL + summary
- Strips HTML tags from content
- Persists last-seen timestamp to disk

**Edge Cases:**
- First run → init with current time (lines 41-45) ✗ NOT TESTED
- Entry has no timestamp → skipped (lines 109-110) ✗ NOT TESTED
- Entry older than 2 days → skipped (lines 112-113) ✗ NOT TESTED
- Entry already seen → skipped (lines 115-116) ✗ NOT TESTED
- Summary > 1000 chars → truncated (lines 97-98) ✓ TESTED
- Parse error → logs, continues (lines 147-148) ✗ NOT TESTED
- HTML entities decoded (lines 79-80) ✓ TESTED

**Configuration Knobs:**
- `rss.url`: RSS feed URL
- `rss.name`: Display name
- `rss.keywords`: Keyword filtering config
- `rss.parser`: Text parsing config
- `DEFAULT_POLL_INTERVAL`: 300 seconds (constant)
- `MAX_ENTRY_AGE_DAYS`: 2 days (constant)

**Timestamp Persistence:** `tmp/rsslog/{rss_name}.txt` (ISO format)

**External Dependencies:** feedparser library, file system, network

**Test Coverage:** 30% (8 tests for formatting/HTML stripping, 0 tests for polling loop)

---

### Feature 5: Parser Rules (Line Trimming)

**Code Location:** [MessageRouter.py:97-161](../src/MessageRouter.py#L97-L161)

**Core Function:**
- `parse_msg(message_data, parser_config)` (lines 97-161)

**Expectations:**
- Trims first N lines if `trim_front_lines` specified
- Trims last N lines if `trim_back_lines` specified
- Returns unchanged text if parser is None
- Returns unchanged text if both values are 0
- Returns placeholder if all lines removed

**Implementation:**
1. Splits text by newlines
2. Removes first N lines: `lines[front:]`
3. Removes last N lines: `lines[:-back]`
4. Rejoins with newlines

**Edge Cases:**
- Negative values → warning, unchanged (lines 120-122) ✗ NOT TESTED
- Both values 0 → unchanged (lines 125-126) ✓ TESTED
- All lines removed → placeholder (lines 135-139) ✗ NOT TESTED
- Invalid config type → warning, unchanged (lines 158-160) ✗ NOT TESTED
- None parser → unchanged (line 157) ✓ TESTED

**Configuration Format:**
```json
{
  "parser": {
    "trim_front_lines": 2,
    "trim_back_lines": 3
  }
}
```

**External Dependencies:** None

**Test Coverage:** 75% (4 tests for trimming, missing negative/invalid cases)

---

### Feature 6: Restricted Mode (Media Filtering)

**Code Location:** [TelegramHandler.py:209-248](../src/TelegramHandler.py#L209-L248)

**Purpose:** Security feature for CTI workflows - blocks malicious media files

**Core Function:**
- `_is_media_restricted(message)` (lines 209-248): Validates media against allow-lists

**Allowed Document Types:**
```python
ALLOWED_MIME_TYPES = {
    "text/plain", "text/csv", "text/xml", "application/sql",
    "application/octet-stream", "application/x-sql",
    "application/x-msaccess", "application/json"
}

ALLOWED_EXTENSIONS = {
    '.txt', '.csv', '.log', '.sql', '.xml',
    '.dat', '.db', '.mdb', '.json'
}
```

**Rules:**
- No media → allowed (not restricted)
- Photos → blocked
- Documents → allowed only if **BOTH** extension AND MIME type match allow-lists
- Other media types (video, audio, etc.) → blocked

**Expectations:**
- Photos always blocked in restricted mode
- Documents validated by both extension and MIME type
- Missing filename or MIME type → blocked
- Non-document media → blocked

**Edge Cases:**
- No media → allowed (line 219) ✓ TESTED
- Photos → blocked (lines 221-223) ✓ TESTED
- Document without filename → blocked (lines 231-237) ✗ NOT TESTED
- Document without MIME type → blocked (lines 239-240) ✗ NOT TESTED
- Extension matches, MIME doesn't → blocked (line 242) ✗ NOT TESTED
- MIME matches, extension doesn't → blocked (line 242) ✗ NOT TESTED

**Configuration Knob:** `restricted_mode: true/false` (per-channel)

**External Dependencies:** Telegram message objects

**Test Coverage:** 40% (2 basic tests, missing document validation scenarios)

---

### Feature 7: Rate Limiting

**Code Location:** [DestinationHandler.py:32-66](../src/DestinationHandler.py#L32-L66)

**Core Functions:**
- `_check_and_wait_for_rate_limit(destination_identifier)` (lines 32-50): Synchronous wait
- `_store_rate_limit(destination_identifier, wait_seconds)` (lines 51-66): Store rate limit

**Expectations:**
- Per-destination tracking via identifier string
- Ceiling rounding for wait times
- Synchronous sleep when rate limited
- Auto-cleanup of expired rate limits
- Discord: extracts `retry_after` from 429 response
- Telegram: extracts `seconds` from FloodWaitError

**Implementation:**
- Storage: `Dict[str, float]` mapping key → expiry timestamp
- Ceiling rounding: `math.ceil(wait_seconds)`
- Synchronous sleep: `time.sleep(wait_time)`
- Auto-cleanup: Expired rate limits deleted after wait

**Discord Implementation** ([DiscordHandler.py:81-90](../src/DiscordHandler.py#L81-L90)):
- HTTP 429 response → parses `retry_after` from JSON body
- Parse error → fallback to 1.0 second

**Telegram Implementation** ([TelegramHandler.py:396-399](../src/TelegramHandler.py#L396-L399)):
- FloodWaitError exception → extracts `e.seconds`

**Edge Cases:**
- Multiple destinations tracked independently ✓ TESTED
- Expired rate limits auto-removed (line 49) ✓ TESTED
- Zero/negative wait → no sleep (line 44) ✓ TESTED
- Ceiling rounding (line 59) ✓ TESTED
- Discord 429 parse failure → 1.0s (lines 88-90) ✗ NOT TESTED
- Telegram FloodWaitError (lines 396-399) ✗ NOT TESTED

**External Dependencies:** time.time(), time.sleep()

**Test Coverage:** 80% (base class well-tested, Telegram FloodWaitError untested)

---

### Feature 8: Message Chunking

**Code Location:** [DestinationHandler.py:68-95](../src/DestinationHandler.py#L68-L95)

**Core Function:**
- `_chunk_text(text, max_length)` (lines 68-95): Splits text at newlines or max length

**Limits:**
- **Discord:** 2000 characters per message ([DiscordHandler.py:18](../src/DiscordHandler.py#L18))
- **Telegram Messages:** 4096 characters ([TelegramHandler.py:22](../src/TelegramHandler.py#L22))
- **Telegram Captions:** 1024 characters ([TelegramHandler.py:21](../src/TelegramHandler.py#L21))

**Algorithm:**
1. If text ≤ max_length → return single chunk
2. Find last newline before limit: `text.rfind('\n', 0, max_length)`
3. If no newline found → hard break at max_length
4. Strip leading newlines from next chunk
5. Repeat until all text processed

**Expectations:**
- Prefers splitting at newlines over mid-word breaks
- Strips leading newlines between chunks
- Handles empty strings
- Handles text exactly at limit
- Handles single lines longer than limit

**Edge Cases:**
- Empty string → [""] ✓ TESTED
- Single line > max → splits at max_length ✓ TESTED
- Exactly at limit → single chunk ✓ TESTED
- Multiple newlines → stripped (line 93) ✓ TESTED
- Newline splitting (line 88) ✓ TESTED

**Telegram Caption Overflow** ([TelegramHandler.py:371-384](../src/TelegramHandler.py#L371-L384)):
- Caption > 1024 → send media captionless, then text chunks ✗ NOT TESTED

**External Dependencies:** None

**Test Coverage:** 90% (base chunking tested, Telegram caption overflow untested)

---

### Feature 9: Retry Queue

**Code Location:** [MessageQueue.py:25-150](../src/MessageQueue.py#L25-L150)

**Core Functions:**
- `enqueue(destination, formatted_content, media_path, reason)` (lines 34-55): Adds failed message
- `process_queue(watchtower)` (lines 57-96): Background async processor
- `_retry_send(retry_item, watchtower)` (lines 98-134): Attempts retry

**Constants:**
- `MAX_RETRIES = 3` (line 28): Total attempts before dropping
- `INITIAL_BACKOFF = 5` seconds (line 29)
- Exponential backoff: 5s, 10s, 20s

**Processing Loop:**
- Polls every 1 second (line 96)
- Checks `next_retry_time` for each item
- Success → removes from queue
- Failure at max retries → drops message
- Failure before max → exponential backoff

**Expectations:**
- Failed messages enqueued with 5s initial backoff
- Backoff doubles on each retry: 5s, 10s, 20s
- After 3 failed attempts, message dropped
- Queue processes asynchronously in background
- Successful retry removes item from queue

**Edge Cases:**
- Queue modification during iteration → copies list (line 68) ✓ TESTED
- Exponential backoff calculation (line 89) ✓ TESTED
- Initial 5s backoff (lines 34-55) ✓ TESTED
- Max retries constant (line 28) ✓ TESTED
- process_queue() async loop (lines 57-96) ✗ NOT TESTED
- _retry_send() Discord path (lines 110-116) ✗ NOT TESTED
- _retry_send() Telegram path (lines 118-128) ✗ NOT TESTED
- Max retries → drop (lines 79-85) ✗ NOT TESTED
- Success → remove (lines 73-78) ✗ NOT TESTED

**External Dependencies:** asyncio.sleep(), Watchtower instance

**Test Coverage:** 60% (enqueue tested, async processing untested)

---

### Feature 10: Metrics Collection

**Code Location:** [MetricsCollector.py:13-106](../src/MetricsCollector.py#L13-L106)

**Core Functions:**
- `increment(metric_name, value=1)` (lines 51-59): Adds to counter
- `set(metric_name, value)` (lines 61-69): Replaces value
- `get(metric_name)` (lines 71-80): Retrieves value
- `get_all()` (lines 82-88): Returns all metrics
- `reset()` (lines 90-94): Clears all metrics
- `reset_metric(metric_name)` (lines 96-105): Clears single metric

**Storage:**
- JSON file at `tmp/metrics.json`
- Auto-saves on every increment/set
- Auto-loads on initialization

**Tracked Metrics** (from [Watchtower.py](../src/Watchtower.py)):

| Metric Name | Type | When Incremented | Line |
|-------------|------|------------------|------|
| `messages_received_telegram` | Counter | Telegram message received | 183 |
| `messages_received_rss` | Counter | RSS entry received | 183 |
| `messages_no_destination` | Counter | No matching destinations | 190 |
| `messages_routed_success` | Counter | Sent to ≥1 destination | 202 |
| `messages_routed_failed` | Counter | Failed to all destinations | 204 |
| `messages_sent_discord` | Counter | Sent to Discord | 348 |
| `messages_sent_telegram` | Counter | Sent to Telegram | 389 |
| `messages_queued_retry` | Counter | Enqueued for retry | 360, 401 |
| `ocr_processed` | Counter | OCR extraction completed | 241 |
| `ocr_sent` | Counter | Message with OCR sent | 350, 391 |
| `time_ran` | Gauge | Runtime in seconds (per-session) | 145 |

**Expectations:**
- Metrics persisted to disk on every change
- Missing file → starts fresh
- Parse error → starts fresh
- Nonexistent metric → returns 0
- `time_ran` is per-session (uses `.set()` not `.increment()`)

**Edge Cases:**
- File doesn't exist → fresh (lines 37-38) ✓ TESTED
- Parse error → fresh (lines 34-36) ✓ TESTED
- Nonexistent metric → 0 (line 80) ✓ TESTED
- Increment creates metric ✓ TESTED
- Large values ✓ TESTED
- reset_metric() (lines 96-105) ✗ NOT TESTED

**External Dependencies:** File system (tmp/metrics.json)

**Test Coverage:** 95% (excellent unit tests, reset_metric untested)

---

### Feature 11: Configuration Loading

**Code Location:** [ConfigManager.py:21-302](../src/ConfigManager.py#L21-L302)

**Core Functions:**
- `__init__()` (lines 24-51): Loads config and creates directories
- `_load_config(config_file)` (lines 53-78): Parses config.json
- `_process_destination_config(destination_config, ...)` (lines 80-114): Processes single destination
- `_resolve_destination_endpoint(destination_config, ...)` (lines 116-147): Gets webhook/channel from env
- `_process_channel_sources(destination_config, ...)` (lines 149-173): Processes Telegram channels
- `_process_rss_sources(destination_config, ...)` (lines 175-202): Processes RSS feeds
- `_resolve_keywords(keyword_config)` (lines 247-291): Resolves keyword files + inline
- `_load_keyword_file(filename)` (lines 204-245): Loads keyword JSON with caching

**Environment Variables:**
- `TELEGRAM_API_ID`: Required
- `TELEGRAM_API_HASH`: Required
- Custom webhook/channel vars via `env_key`

**Configuration Structure:**
```json
{
  "destinations": [
    {
      "name": "Discord Feed",
      "type": "discord",
      "env_key": "DISCORD_WEBHOOK_URL",
      "channels": [
        {
          "id": "@channel_username",
          "keywords": {
            "files": ["kw-general.json"],
            "inline": ["CVE"]
          },
          "restricted_mode": false,
          "parser": {"trim_front_lines": 1, "trim_back_lines": 2},
          "ocr": true
        }
      ],
      "rss": [
        {
          "url": "https://example.com/feed.xml",
          "name": "Security Feed",
          "keywords": {...},
          "parser": {...}
        }
      ]
    }
  ]
}
```

**RSS Deduplication:** Feeds with same URL deduplicated globally (lines 75-76, 189-193)

**Expectations:**
- Loads config from JSON file
- Validates required env vars (API_ID, API_HASH)
- Resolves destination endpoints from env vars
- Loads keywords from files with caching
- Deduplicates RSS feeds globally
- Creates required directories (tmp/attachments, tmp/rsslog)

**Edge Cases:**
- Missing API credentials → ValueError (lines 28-29) ✗ NOT TESTED
- Config file not found → ValueError (line 56) ✗ NOT TESTED
- No valid destinations → ValueError (line 73) ✗ NOT TESTED
- Missing env_key → warning, skip (lines 127, 138) ✗ NOT TESTED
- Empty channels → valid (lines 99-101) ✓ TESTED
- Keywords None → forward all (lines 260-261) ✗ NOT TESTED
- Keyword file caching (lines 217-218) ✓ TESTED
- RSS deduplication (lines 75-76, 189-193) ✗ NOT TESTED

**External Dependencies:** File system, environment variables

**Test Coverage:** 30% (basic loading tested, missing edge cases and error paths)

---

### Feature 12: Media Handling

**Download Location:** [TelegramHandler.py:250-258](../src/TelegramHandler.py#L250-L258)
**Cleanup:** [Watchtower.py:87-101, 213-219](../src/Watchtower.py#L87-L101)

**Core Functions:**
- `download_media(message_data)` (lines 250-258): Downloads media to `tmp/attachments/`
- `_cleanup_attachments_dir()` (lines 87-101): Removes leftover files on startup
- Media cleanup after processing (lines 213-219)

**Media Decision Logic** ([Watchtower.py:253-286](../src/Watchtower.py#L253-L286)):
- OCR needed && no media_path → downloads
- Any destination needs media → downloads
- Restricted mode blocks → skips if all destinations have restrictions

**File Storage:** `tmp/attachments/{telegram_file_id}.{ext}`

**Expectations:**
- Media downloaded to temp directory
- Files cleaned up after message processing
- Leftover files from crashes cleaned on startup
- Download failures return None
- Already-downloaded media reused

**Edge Cases:**
- Media already downloaded → reuse (line 234) ✗ NOT TESTED
- Download fails → None (lines 256-258) ✗ NOT TESTED
- Media path doesn't exist → cleanup logs error (lines 218-219) ✗ NOT TESTED
- Leftover files from crash → cleaned (lines 87-101) ✗ NOT TESTED

**External Dependencies:** Telegram API, file system

**Test Coverage:** 0% (completely untested)

---

### Feature 13: Reply Context Extraction

**Code Location:** [TelegramHandler.py:182-207](../src/TelegramHandler.py#L182-L207)

**Core Function:**
- `_get_reply_context(message)` (lines 182-207): Extracts original message info

**Extracted Fields:**
- `message_id`: Original message ID
- `author`: Username of original sender
- `text`: Original message text (or empty)
- `time`: Original message timestamp (UTC string)
- `media_type`: Type of original media
- `has_media`: Boolean

**Formatting:**
- **Discord** ([DiscordHandler.py:123-140](../src/DiscordHandler.py#L123-L140)): `**Replying to:** {author} ({time})`
- **Telegram** ([TelegramHandler.py:448-469](../src/TelegramHandler.py#L448-L469)): `<b>Replying to:</b> {author} ({time})`

**Expectations:**
- Fetches original message from Telegram
- Extracts author, text, timestamp, media type
- Text > 200 chars → truncated with "..."
- Media only, no caption → placeholder text
- Fetch failures → returns None

**Edge Cases:**
- Reply fetch fails → None (lines 204-206) ✗ NOT TESTED
- Text > 200 chars → truncated (lines 133-135, 463-464) ✗ NOT TESTED
- Media only → placeholder (lines 137-138, 466-467) ✗ NOT TESTED

**External Dependencies:** Telegram API

**Test Coverage:** 0% (completely untested)

---

### Feature 14: URL Defanging

**Code Location:** [TelegramHandler.py:261-301](../src/TelegramHandler.py#L261-L301), [Watchtower.py:243-251](../src/Watchtower.py#L243-L251)

**Purpose:** CTI safety - makes t.me links non-clickable

**Core Functions:**
- `_defang_tme(url)` (lines 261-272): Replaces protocols and dots
- `build_message_url(channel_id, channel_name, message_id)` (lines 275-295): Builds t.me link
- `build_defanged_tg_url(...)` (lines 298-300): Combines above

**Defanging Rules:**
- `https://t.me` → `hxxps://t[.]me`
- `http://t.me` → `hxxp://t[.]me`
- `https://telegram.me` → `hxxps://telegram[.]me`
- `http://telegram.me` → `hxxp://telegram[.]me`

**URL Building:**
- Public channel: `https://t.me/{username}/{message_id}`
- Private channel: `https://t.me/c/{internal_id}/{message_id}`
- Internal ID: strips `-100` prefix from channel_id

**Integration** ([Watchtower.py:243-251](../src/Watchtower.py#L243-L251)):
- Stored in `message_data.metadata['src_url_defanged']`
- Displayed in formatted messages

**Edge Cases:**
- https://t.me → hxxps://t[.]me ✓ TESTED
- http://t.me → hxxp://t[.]me ✓ TESTED
- https://telegram.me → hxxps://telegram[.]me ✓ TESTED
- http://telegram.me → hxxp://telegram[.]me ✓ TESTED
- Public channel URL building (line 286) ✓ TESTED
- Private channel URL building (lines 288-295) ✓ TESTED
- -100 prefix stripping (lines 291-294) ✓ TESTED
- Defanged URL display in messages (lines 100-102, 422-424) ✗ NOT TESTED

**External Dependencies:** None

**Test Coverage:** 90% (defanging well-tested, display untested)

---

### Feature 15: Message Formatting

**Discord Format** ([DiscordHandler.py:92-141](../src/DiscordHandler.py#L92-L141)):
```markdown
**New message from:** {channel_name}
**By:** {username}
**Time:** {timestamp}
**Source:** {defanged_url}  [if present]
**Content:** {media_type}  [if has_media]
**Matched:** `keyword1`, `keyword2`  [if keywords]
**Replying to:** {reply_author} ({reply_time})  [if reply]
**  Original content:** {reply_media_type}
**  Original message:** {reply_text}
**Message:**
{message_text}
**OCR:**
> {ocr_text}
```

**Telegram Format** ([TelegramHandler.py:405-469](../src/TelegramHandler.py#L405-L469)):
```html
<b>New message from:</b> {channel_name}
<b>By:</b> {username}
<b>Time:</b> {timestamp}
<b>Source:</b> {defanged_url}  [if present]
<b>Content:</b> {media_type}  [if has_media]
<b>Matched:</b> <code>keyword1</code>, <code>keyword2</code>  [if keywords]
<b>Replying to:</b> {reply_author} ({reply_time})  [if reply]
<b>  Original content:</b> {reply_media_type}
<b>  Original message:</b> {reply_text}
<b>Message:</b>
{message_text}
<b>OCR:</b>
<blockquote>{ocr_text}</blockquote>
```

**Expectations:**
- Discord uses Markdown syntax
- Telegram uses HTML with html.escape() for safety
- Optional fields only shown if present
- Keywords displayed as comma-separated list
- OCR text quoted/blockquoted

**Edge Cases:**
- Basic formatting ✓ TESTED
- Keyword display (lines 107-109, 429-431) ✓ TESTED
- HTML escaping (lines 414-446) ✓ TESTED
- Reply context formatting (lines 123-140, 448-469) ✗ NOT TESTED
- OCR text formatting (lines 116-119, 439-443) ✗ NOT TESTED
- Defanged URL display (lines 100-102, 422-424) ✗ NOT TESTED
- Media type display (lines 104-105, 426-427) ✗ NOT TESTED

**External Dependencies:** None

**Test Coverage:** 60% (basic formatting tested, optional fields untested)

---

### Feature 16: Multiple Destinations

**Code Location:** [MessageRouter.py:41-95](../src/MessageRouter.py#L41-L95), [Watchtower.py:196-206](../src/Watchtower.py#L196-L206)

**Logic:** One source channel can route to multiple destinations with different keywords/parsers

**Example Config:**
```json
{
  "destinations": [
    {
      "name": "Personal Feed",
      "type": "telegram",
      "channels": [{"id": "@channel", "keywords": ["CVE"]}]
    },
    {
      "name": "Work Feed",
      "type": "discord",
      "channels": [{"id": "@channel", "keywords": ["ransomware"]}]
    }
  ]
}
```

**Processing** ([Watchtower.py:196-206](../src/Watchtower.py#L196-L206)):
- Iterates all destinations
- Counts successes
- Returns true if ANY destination succeeded
- Tracks metrics separately

**Expectations:**
- Same channel with different keywords → both evaluated
- One destination fails → others still attempted
- Parser applied per-destination
- Media downloaded once, used by all
- Success if ANY destination succeeds

**Edge Cases:**
- Same channel, different keywords ✓ TESTED
- One destination fails → others proceed ✗ NOT TESTED
- Parser applied per-destination ✓ TESTED
- Media downloaded once ✗ NOT TESTED

**External Dependencies:** None

**Test Coverage:** 70% (basic tested, failure scenarios untested)

---

### Feature 17: Message Pipeline

**Code Location:** [Watchtower.py:165-220](../src/Watchtower.py#L165-L220)

**Flow:**
1. `_handle_message()` receives MessageData
2. Skip if `is_latest=True` (connection proof)
3. Track incoming message metric
4. **Preprocessing:** OCR extraction, URL defanging
5. **Routing:** Get matching destinations
6. No destinations → track metric, return
7. **Media restrictions:** Check if media allowed
8. **For each destination:** Parse, format, send
9. **Cleanup:** Delete media file
10. Track routing metrics

**Expectations:**
- Messages processed asynchronously
- OCR extraction for channels with ocr=true
- URL defanging for all Telegram messages
- Media downloaded if needed
- Restricted mode filters media
- Cleanup runs even on errors (finally block)

**Edge Cases:**
- is_latest=True → skipped ✗ NOT TESTED
- No destinations → logged ✗ NOT TESTED
- Media restrictions → skip download ✗ NOT TESTED
- Error → cleanup still runs ✗ NOT TESTED

**External Dependencies:** TelegramHandler, RSSHandler, MessageRouter, DestinationHandler subclasses

**Test Coverage:** 0% (completely untested)

---

### Feature 18: Channel Discovery

**Code Location:** [Watchtower.py:585-687](../src/Watchtower.py#L585-L687)

**Purpose:** Auto-discover accessible Telegram channels/groups/bots

**Core Function:**
- `discover_channels(diff_mode=False, generate_config=False)` (lines 585-687)

**Modes:**
1. **List mode** (default): Shows all accessible dialogs
2. **Diff mode** (`--diff`): Compares with existing config.json
3. **Generate mode** (`--generate`): Creates config_discovered.json

**Output:**
- Entity type (Channel/Supergroup/Group/Bot/User)
- Entity name
- Channel identifier (@username or numeric ID)

**Expectations:**
- Fetches all accessible Telegram dialogs
- Skips self (authenticated user)
- Prefers @username for public channels
- Uses numeric ID for private channels/groups
- Generate mode creates template config

**Edge Cases:**
- Skips self (lines 622-623) ✗ NOT TESTED
- Public channels → @username (line 627) ✗ NOT TESTED
- Private channels → numeric ID (line 627) ✗ NOT TESTED
- Generate mode → config_discovered.json (lines 629-687) ✗ NOT TESTED

**External Dependencies:** Telegram API

**Test Coverage:** 0% (CLI command, not tested)

---

## PART 4: TEST FILE INVENTORY AND COVERAGE MAPPING

### Test File 1: test_core.py (43 test methods)

**Tested Classes/Functions:**

#### ConfigManager Tests (2 tests)

| Test Method | Source Coverage | Line Ref | Status |
|-------------|----------------|----------|--------|
| `test_load_config_destinations_key` | `__init__`, `_load_config` | [ConfigManager.py:24-78](../src/ConfigManager.py#L24-L78) | ✓ Basic loading |
| `test_combine_keyword_files_and_inline` | `_resolve_keywords` | [ConfigManager.py:247-291](../src/ConfigManager.py#L247-L291) | ✓ Keyword combining |

**Gaps:**
- ✗ RSS deduplication
- ✗ Invalid JSON handling
- ✗ Missing env vars
- ✗ Multiple destinations
- ✗ Error paths

---

#### MessageRouter Tests (11 tests)

| Test Method | Source Coverage | Assertions |
|-------------|----------------|------------|
| `test_match_keywords_case_insensitive` | `get_destinations` line 91 | ✓ Case-insensitive |
| `test_empty_keywords_forwards_all` | `get_destinations` lines 88-89 | ✓ Empty keywords |
| `test_parser_trim_front_lines` | `parse_msg` lines 129-130 | ✓ Front trim |
| `test_parser_trim_back_lines` | `parse_msg` lines 131-132 | ✓ Back trim |
| `test_parser_both_trim_directions` | `parse_msg` lines 129-132 | ✓ Both directions |
| `test_parser_no_trimming` | `parse_msg` line 157 | ✓ None parser |
| `test_channel_match_numeric_id` | `_channel_matches` lines 185-186 | ✓ Numeric ID |
| `test_keyword_matching_ocr_text` | `get_destinations` lines 82-84 | ✓ OCR in search |
| `test_no_match_wrong_channel` | `get_destinations` lines 66-68 | ✓ No match |
| `test_multiple_keyword_matches` | `get_destinations` lines 91-93 | ✓ Multiple keywords |
| `test_rss_source_routing` | `_channel_matches` lines 181-182 | ✓ RSS URL matching |

**Gaps:**
- ✗ `is_channel_restricted()` - NOT TESTED
- ✗ `is_ocr_enabled_for_channel()` - NOT TESTED
- ✗ -100 prefix handling
- ✗ Negative parser values
- ✗ Parser removes all content

---

#### MessageData Tests (6 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_create_from_telegram` | ✓ Dataclass creation |
| `test_create_from_rss` | ✓ Dataclass creation |
| `test_store_metadata` | ✓ Metadata field |
| `test_optional_fields_defaults` | ✓ Default values |
| `test_metadata_defaults_empty_dict` | ✓ default_factory |
| `test_timestamp_timezone_aware` | ✓ Timestamp field |

**Coverage:** 100% complete

---

#### MessageQueue Tests (9 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_enqueue_sets_5s_backoff` | ✓ Initial backoff |
| `test_exponential_backoff` | ✓ 5s→10s→20s |
| `test_queue_size_tracking` | ✓ Size tracking |
| `test_clear_queue` | ✓ Queue clear |
| `test_enqueue_with_media_path` | ✓ Media storage |
| `test_enqueue_multiple_items` | ✓ Order preserved |
| `test_max_retries_constant` | ✓ Constant = 3 |
| `test_initial_backoff_constant` | ✓ Constant = 5 |
| `test_retry_item_defaults` | ✓ Default values |

**Gaps:**
- ✗ `process_queue()` async loop - CRITICAL
- ✗ `_retry_send()` Discord/Telegram - CRITICAL
- ✗ Max retries → drop message
- ✗ Success → remove from queue

---

#### MetricsCollector Tests (13 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_increment_metric` | ✓ Basic increment |
| `test_increment_by_value` | ✓ Custom value |
| `test_get_all_metrics` | ✓ Returns all |
| `test_save_and_load_json` | ✓ Persistence |
| `test_reset_all_metrics` | ✓ Clear all |
| `test_get_nonexistent_metric` | ✓ Returns 0 |
| `test_increment_creates_metric` | ✓ Auto-create |
| `test_persistence_after_reset` | ✓ Persists empty |
| `test_increment_large_value` | ✓ Large numbers |
| `test_multiple_increments_same_metric` | ✓ Accumulation |
| `test_concurrent_metrics` | ✓ Multiple metrics |
| `test_set_metric` | ✓ Set replaces |
| `test_set_vs_increment` | ✓ Semantic difference |

**Coverage:** 95% (excellent)

**Gap:**
- ✗ `reset_metric(metric_name)`

---

#### Watchtower Tests (2 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_default_components_created` | ✓ Initialization |
| `test_inject_mocks` | ✓ DI pattern |

**Coverage:** 20% (only init)

**Gaps:**
- ✗ `start()` - CRITICAL
- ✗ `shutdown()` - CRITICAL
- ✗ `_handle_message()` - CRITICAL
- ✗ `_preprocess_message()` - CRITICAL
- ✗ All pipeline methods - CRITICAL

---

### Test File 2: test_handlers.py (26 test methods)

**Tested Classes/Functions:**

#### DestinationHandler Tests (9 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_rate_limit_ceiling_rounding` | ✓ Ceiling rounding |
| `test_chunk_text_under_limit` | ✓ Under limit |
| `test_chunk_text_over_limit` | ✓ Over limit |
| `test_chunk_text_exact_limit` | ✓ Exact limit |
| `test_rate_limit_multiple_destinations` | ✓ Per-destination |
| `test_rate_limit_expiry_check` | ✓ Expiry check |
| `test_chunk_text_preserves_newlines` | ✓ Newline splitting |
| `test_chunk_text_empty_string` | ✓ Empty string |
| `test_chunk_text_single_long_line` | ✓ Hard break |

**Coverage:** 90% (excellent base class testing)

---

#### DiscordHandler Tests (10 tests)

| Test Method | Coverage | Mocks |
|-------------|----------|-------|
| `test_inherits_destination_handler` | ✓ Hierarchy | - |
| `test_format_message_markdown` | ✓ Markdown format | - |
| `test_format_message_with_keywords` | ✓ Keyword display | - |
| `test_send_message_success` | ✓ Success path | requests.post→200 |
| `test_handle_429_response` | ✓ Rate limit | requests.post→429 |
| `test_send_message_with_media` | ✓ Media upload | requests.post, file |
| `test_send_message_network_error` | ✓ Exception | requests.post raises |
| `test_send_message_500_error` | ✓ Server error | requests.post→500 |
| `test_format_message_includes_all_fields` | ✓ All fields | - |
| `test_chunked_message_sends_multiple` | ✓ Chunking | requests.post |

**Coverage:** 75%

**Gaps:**
- ✗ Reply context formatting
- ✗ OCR text formatting
- ✗ Defanged URL display
- ✗ Media type display
- ✗ Chunking with media (first has media, rest text)

---

#### TelegramHandler Tests (14 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_inherits_destination_handler` | ✓ Hierarchy |
| `test_format_message_html` | ✓ HTML format |
| `test_defang_url` | ✓ URL defanging |
| `test_build_message_url_public` | ✓ Public URL |
| `test_build_message_url_private` | ✓ Private URL |
| `test_restricted_mode_blocks_photo` | ✓ Photo blocking |
| `test_no_media_is_allowed` | ✓ No media |
| `test_format_message_with_keywords` | ✓ Keyword display |
| `test_defang_multiple_protocols` | ✓ All protocols |
| `test_build_message_url_numeric_public` | ✓ Numeric channel |
| `test_format_message_escapes_html` | ✓ HTML escaping |
| `test_send_message_creates_client` | ✓ Client init |
| `test_caption_limit_constant` | ✓ Constant value |
| `test_caption_length_validation_logic` | ✓ Limit validation |

**Coverage:** 40%

**Gaps (CRITICAL):**
- ✗ `start()` - Telegram client connection
- ✗ `setup_handlers()` - Message handlers
- ✗ `_create_message_data()` - Message parsing
- ✗ `_get_reply_context()` - Reply extraction
- ✗ `_is_media_restricted()` documents - Extension/MIME validation
- ✗ `download_media()` - Media download
- ✗ `send_copy()` - CRITICAL send path
- ✗ Caption > 1024 handling - CRITICAL
- ✗ FloodWaitError handling

---

#### OCRHandler Tests (6 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_is_available_false_when_no_easyocr` | ✓ Not installed |
| `test_extract_text_success` | ✓ Success path |
| `test_extract_text_empty_result` | ✓ Empty result |
| `test_extract_text_when_unavailable` | ✓ Unavailable check |
| `test_extract_text_handles_error` | ✓ Error handling |
| `test_reader_initialization_once` | ✓ Lazy init |

**Coverage:** 95% (excellent)

---

#### RSSHandler Tests (8 tests)

| Test Method | Coverage |
|-------------|----------|
| `test_strip_html_tags` | ✓ HTML stripping |
| `test_strip_html_entities` | ✓ Entity decoding |
| `test_format_entry_truncate_summary` | ✓ Truncation |
| `test_strip_html_nested_tags` | ✓ Nested tags |
| `test_strip_html_preserves_newlines` | ✓ Newlines |
| `test_format_entry_no_summary` | ✓ No summary |
| `test_format_entry_with_html_in_title` | ✓ HTML in title |
| `test_format_entry_special_characters` | ✓ Special chars |

**Coverage:** 30% (only formatting)

**Gaps (CRITICAL):**
- ✗ `run_feed()` polling loop
- ✗ `_process_entry()` entry processing
- ✗ `_read_last_ts()` / `_write_last_ts()` persistence
- ✗ MAX_ENTRY_AGE_DAYS filtering
- ✗ Parse error handling

---

### Test File 3: test_integration.py (13 test methods)

| Test Method | Coverage |
|-------------|----------|
| `test_full_pipeline_text_only` | ✓ Basic Telegram→Discord |
| `test_discord_429_enqueue` | ✓ 429→enqueue |
| `test_metrics_increment_on_operations` | ✓ Metrics tracking |
| `test_keyword_matching_forwards_correctly` | ✓ Keyword filtering |
| `test_same_channel_multiple_destinations` | ✓ Multiple destinations |
| `test_parser_trims_lines` | ✓ Parser integration |
| `test_discord_network_error_recovery` | ✓ Network error |
| `test_empty_message_handling` | ✓ Empty message |
| `test_malformed_config_handling` | ✓ Empty config |
| `test_media_with_ocr_extraction` | ✓ OCR + keywords |
| `test_queue_backoff_progression` | ✓ Backoff calc |
| `test_queue_drop_after_max_retries` | ✓ Max retries |
| `test_multiple_channels_same_destination` | ✓ Multiple sources |
| `test_mixed_source_types` | ✓ Telegram + RSS |
| `test_caption_limit_constant` | ✓ Telegram constant |
| `test_no_content_loss_with_long_caption_and_media` | ✓ Chunking validation |
| `test_chunking_respects_message_boundaries` | ✓ Multi-chunk order |
| `test_ocr_sent_metric_tracked` | ✓ OCR metric |
| `test_ocr_sent_not_tracked_without_ocr` | ✓ OCR conditional |
| `test_time_ran_metric_per_session` | ✓ time_ran behavior |

**Coverage:** 35% (basic flows)

**Gaps (CRITICAL):**
- ✗ RSS → Discord flow
- ✗ RSS → Telegram flow
- ✗ Telegram → Telegram flow
- ✗ Media download → restricted mode → skip
- ✗ Media download → send to Discord
- ✗ Media download → send to Telegram
- ✗ OCR extraction → download media → process
- ✗ Reply context extraction → format → send
- ✗ Retry queue async processing
- ✗ Multiple async sources concurrently
- ✗ Startup/shutdown cleanup
- ✗ FloodWaitError → enqueue

---

## PART 5: EXTERNAL DEPENDENCIES AND MOCK BOUNDARIES

### Network Calls

| Dependency | Location | Mocked in Tests? | Real Calls? |
|------------|----------|------------------|-------------|
| **Telegram API** | TelegramHandler.client (telethon) | ✓ Mocked (all tests) | No |
| **Discord Webhooks** | requests.post() in DiscordHandler | ✓ Mocked (handler tests) | No |
| **RSS Feeds** | feedparser.parse() in RSSHandler | ✗ NOT mocked | NO TESTS |

### File I/O

| Operation | Location | Mocked in Tests? | Real Files? |
|-----------|----------|------------------|-------------|
| **Config JSON** | ConfigManager._load_config() | ✓ Mocked (mock_open) | No |
| **Keyword JSON** | ConfigManager._load_keyword_file() | ✓ Mocked (mock_open) | No |
| **Metrics JSON** | MetricsCollector | ✗ NOT mocked | **Yes (temp files)** |
| **RSS timestamp files** | RSSHandler._read_last_ts() | - | NO TESTS |
| **Media downloads** | TelegramHandler.download_media() | - | NO TESTS |
| **Attachment cleanup** | Watchtower._cleanup_attachments_dir() | - | NO TESTS |

### Time/Clock Operations

| Operation | Location | Mocked in Tests? | Real Time? |
|-----------|----------|------------------|------------|
| **Rate limit expiry** | DestinationHandler._rate_limits | ✗ NOT mocked | **Yes** |
| **Retry backoff** | MessageQueue.next_retry_time | ✗ NOT mocked | **Yes** |
| **RSS timestamps** | RSSHandler._extract_entry_timestamp() | - | NO TESTS |
| **Metrics time_ran** | Watchtower._start_time | ✗ NOT mocked | **Yes** |

### Environment Variables

| Variable | Usage | Mocked in Tests? | Required? |
|----------|-------|------------------|-----------|
| TELEGRAM_API_ID | Telegram auth | ✓ Mocked (os.getenv) | Yes |
| TELEGRAM_API_HASH | Telegram auth | ✓ Mocked (os.getenv) | Yes |
| DISCORD_WEBHOOK_* | Discord webhooks | ✓ Mocked (os.getenv) | Per destination |
| TELEGRAM_CHANNEL_* | Telegram destinations | ✓ Mocked (os.getenv) | Per destination |

---

## PART 6: TEST QUALITY ASSESSMENT

### Isolation and Mocking

**✓ Well-Isolated:**
- Telegram API calls: Mocked via `@patch('telethon.TelegramClient')`
- Discord webhooks: Mocked via `@patch('requests.post')`
- Config files: Mocked via `mock_open`
- Keyword files: Mocked via `mock_open`

**✗ Not Properly Isolated:**
- Metrics JSON: Uses real temp files (could cause test pollution)
- Time operations: Uses real time.time() (could cause flakiness)
- RSS feeds: Not tested (would need feedparser mocking)

**Boundary Violations:**
- Some tests use real file I/O for metrics (should use temp directories or mocks)
- No tests mock asyncio.sleep() for async operations

### Edge Case Coverage

**Well-Covered Edge Cases:**
- Empty strings in chunking ✓
- Exact-length messages in chunking ✓
- Case-insensitive keyword matching ✓
- Empty keywords → forward all ✓
- OCR library not installed ✓
- OCR processing failures ✓
- HTML entity decoding ✓
- Multiple protocols in defanging ✓

**Missing Edge Cases:**
- Parser removes all lines → placeholder ✗
- Negative parser values → warning ✗
- -100 prefix handling in channel IDs ✗
- Document extension + MIME validation in restricted mode ✗
- Caption > 1024 chars with media ✗
- Media download failures ✗
- Reply text > 200 chars truncation ✗
- RSS entry without timestamp ✗

### Error Handling Coverage

**Tested Error Paths:**
- Discord webhook network errors ✓
- Discord webhook 500 errors ✓
- Discord webhook 429 rate limits ✓
- OCR processing exceptions ✓
- Metrics JSON parse errors ✓ (partial)

**Untested Error Paths:**
- Config file not found ✗
- Config JSON parse errors ✗
- Keyword file not found ✗
- Keyword file invalid JSON ✗
- Telegram FloodWaitError ✗
- Telegram send exceptions ✗
- RSS feed parse errors ✗
- RSS feed poll exceptions ✗
- Media download exceptions ✗
- Attachment cleanup exceptions ✗
- Top-level message handling exceptions ✗
- Async task cancellation ✗

### Integration Test Realism

**Realistic Aspects:**
- Uses actual message data structures ✓
- Tests keyword matching with real config format ✓
- Tests chunking with actual character limits ✓
- Tests metrics persistence ✓

**Unrealistic Aspects:**
- No async operation testing (process_queue, run_feed, _handle_message) ✗
- No concurrent source testing (multiple RSS + Telegram) ✗
- No realistic Telegram message payloads ✗
- No realistic RSS feed XML payloads ✗
- No startup/shutdown lifecycle testing ✗
- No media download/cleanup testing ✗

---

## PART 7: CRITICAL GAPS IN TEST COVERAGE

### CRITICAL GAPS (High Risk, No Tests)

#### Gap 1: Async Message Pipeline

**Location:** [Watchtower.py:165-220](../src/Watchtower.py#L165-L220)

**Untested Functions:**
- `_handle_message()` - Main async message handler
- `_preprocess_message()` - OCR extraction + URL defanging
- `_handle_media_restrictions()` - Media restriction logic
- `_dispatch_to_destination()` - Destination dispatch
- `_send_to_discord()` - Discord send wrapper
- `_send_to_telegram()` - Telegram send wrapper

**Risk:** **CRITICAL**
- **Impact:** Messages could be lost, misrouted, or malformed
- **Likelihood:** High (complex async logic)
- **User Impact:** Complete application failure

**Why Critical:**
- This is the core message processing pipeline
- Handles OCR extraction, routing, media restrictions, cleanup
- No tests verify end-to-end flow
- Error handling untested (try/finally cleanup)

---

#### Gap 2: RSS Feed Polling

**Location:** [RSSHandler.py:132-189](../src/RSSHandler.py#L132-L189)

**Untested Functions:**
- `run_feed()` - Infinite polling loop
- `_process_entry()` - Entry processing logic
- `_read_last_ts()` - Timestamp persistence
- `_write_last_ts()` - Timestamp persistence
- `_extract_entry_timestamp()` - Timestamp extraction

**Risk:** **CRITICAL**
- **Impact:** RSS feeds could fail silently or flood messages
- **Likelihood:** Medium (external dependency)
- **User Impact:** No RSS messages received or duplicate messages

**Why Critical:**
- Entire RSS pipeline has 0% test coverage
- Timestamp persistence untested (could lose state)
- MAX_ENTRY_AGE_DAYS filtering untested (could flood old entries)
- Parse error handling untested (could crash on bad feeds)

---

#### Gap 3: Retry Queue Processing

**Location:** [MessageQueue.py:57-134](../src/MessageQueue.py#L57-L134)

**Untested Functions:**
- `process_queue()` - Background async processor
- `_retry_send()` - Retry send logic

**Risk:** **CRITICAL**
- **Impact:** Failed messages lost forever
- **Likelihood:** Medium (async complexity)
- **User Impact:** Message loss on transient failures

**Why Critical:**
- Background task processing completely untested
- Success → removal logic untested
- Max retries → drop logic untested
- Could retry forever or never retry

---

#### Gap 4: Telegram Send Operations

**Location:** [TelegramHandler.py:347-403](../src/TelegramHandler.py#L347-L403)

**Untested Function:**
- `send_copy()` - Main send path for Telegram

**Untested Scenarios:**
- Caption > 1024 → captionless media + text chunks (lines 371-384)
- Message > 4096 → multiple text chunks
- FloodWaitError → enqueue for retry (lines 396-399)

**Risk:** **CRITICAL**
- **Impact:** Content loss on long captions
- **Likelihood:** High (long messages common)
- **User Impact:** Truncated/lost message content

**Why Critical:**
- Main Telegram send path has 0% test coverage
- Caption overflow handling is complex (lines 371-384)
- Could lose content if chunking logic fails
- FloodWaitError handling untested

---

#### Gap 5: Media Download

**Location:** [TelegramHandler.py:250-258](../src/TelegramHandler.py#L250-L258)

**Untested Function:**
- `download_media()` - Media download from Telegram

**Risk:** **HIGH**
- **Impact:** OCR fails, media forwarding fails
- **Likelihood:** Medium (network dependency)
- **User Impact:** Missing media, no OCR

**Why Critical:**
- Required for OCR feature
- Required for media forwarding
- Download failures completely unhandled in tests
- Cleanup logic untested (could leak disk space)

---

#### Gap 6: OCR Integration Flow

**Location:** [Watchtower.py:230-241](../src/Watchtower.py#L230-L241)

**Untested Logic:**
- OCR trigger logic (`is_ocr_enabled_for_channel`)
- Media download → OCR → keyword matching flow
- OCR failure handling in pipeline

**Risk:** **MEDIUM**
- **Impact:** OCR feature broken
- **Likelihood:** Low (OCR library tested separately)
- **User Impact:** No OCR extraction

**Why Important:**
- OCR library tested in isolation (95% coverage)
- Integration with pipeline untested
- `is_ocr_enabled_for_channel` function never called in tests

---

#### Gap 7: Reply Context Extraction

**Location:** [TelegramHandler.py:182-207](../src/TelegramHandler.py#L182-L207)

**Untested Function:**
- `_get_reply_context()` - Fetch original message from Telegram

**Untested Scenarios:**
- Reply fetch success
- Reply fetch failure → None
- Text > 200 chars → truncation
- Media only → placeholder

**Risk:** **MEDIUM**
- **Impact:** Missing reply context in messages
- **Likelihood:** Medium (Telegram API dependency)
- **User Impact:** Lost context information

---

### SIGNIFICANT GAPS (Medium Risk, Partial Tests)

#### Gap 8: Restricted Mode Complete Validation

**Location:** [TelegramHandler.py:209-248](../src/TelegramHandler.py#L209-L248)

**Tested:** Photos blocked ✓, No media allowed ✓

**Untested:**
- Document with extension + MIME match → allowed
- Document with extension but wrong MIME → blocked
- Document with MIME but wrong extension → blocked
- Document without filename → blocked
- Document without MIME → blocked

**Risk:** **HIGH** (security feature)
- **Impact:** Security bypass (malicious media allowed)
- **Likelihood:** Low (requires specific attack)
- **User Impact:** Malware/exploits in CTI feeds

---

#### Gap 9: Configuration Loading Edge Cases

**Location:** [ConfigManager.py:21-302](../src/ConfigManager.py#L21-L302)

**Tested:** Basic loading ✓, Keyword combining ✓

**Untested:**
- Missing API credentials → ValueError
- Config file not found → ValueError
- Invalid JSON → error
- Missing env_key → skip destination
- No valid destinations → ValueError
- RSS deduplication (lines 75-76, 189-193)

**Risk:** **MEDIUM**
- **Impact:** Application fails to start
- **Likelihood:** Medium (user error)
- **User Impact:** Confusing error messages

---

#### Gap 10: Message Formatting Optional Fields

**Location:** [DiscordHandler.py:92-141](../src/DiscordHandler.py#L92-L141), [TelegramHandler.py:405-469](../src/TelegramHandler.py#L405-L469)

**Tested:** Basic formatting ✓, Keyword display ✓, HTML escaping ✓

**Untested:**
- Reply context formatting (lines 123-140, 448-469)
- OCR text formatting (lines 116-119, 439-443)
- Defanged URL display (lines 100-102, 422-424)
- Media type display (lines 104-105, 426-427)

**Risk:** **LOW**
- **Impact:** Missing information in messages
- **Likelihood:** Low (formatting is straightforward)
- **User Impact:** Incomplete message display

---

#### Gap 11: Chunking with Media

**Location:** [TelegramHandler.py:371-384](../src/TelegramHandler.py#L371-L384), [DiscordHandler.py:45-60](../src/DiscordHandler.py#L45-L60)

**Tested:** Basic chunking ✓, Text-only chunking ✓

**Untested:**
- Chunking with media (first chunk has media, rest text-only)
- Telegram caption > 1024 → captionless + chunks
- Discord media + chunked text

**Risk:** **HIGH**
- **Impact:** Content loss on long captions
- **Likelihood:** High (long messages common)
- **User Impact:** Truncated messages

---

### MINOR GAPS (Low Risk, Mostly Tested)

#### Gap 12: Parser Edge Cases

**Tested:** Basic trimming ✓, Both directions ✓, No trimming ✓

**Untested:**
- Negative values → warning
- All content removed → placeholder
- Invalid config type → warning

**Risk:** **LOW** (edge cases unlikely in practice)

---

#### Gap 13: Channel Matching -100 Prefix

**Tested:** Basic numeric matching ✓, RSS URL matching ✓

**Untested:**
- -100 prefix handling for supergroups (lines 189-194)

**Risk:** **LOW** (most channels work without this)

---

#### Gap 14: Metrics Integration

**Tested:** MetricsCollector class 95% ✓, ocr_sent ✓, time_ran ✓

**Untested:**
- messages_received_telegram integration
- messages_received_rss integration
- messages_no_destination integration
- messages_routed_success/failed integration
- messages_sent_discord integration
- messages_sent_telegram integration
- messages_queued_retry integration
- ocr_processed integration

**Risk:** **LOW** (class well-tested, integration straightforward)

---

#### Gap 15: Startup/Shutdown

**Location:** [Watchtower.py:103-163](../src/Watchtower.py#L103-L163)

**Untested:**
- `start()` - Application startup
- `shutdown()` - Application shutdown
- Attachment cleanup on startup (lines 87-101)
- Metrics finalization on shutdown (line 145)

**Risk:** **LOW**
- **Impact:** Leftover files, incomplete metrics
- **Likelihood:** Low (simple logic)
- **User Impact:** Minor cleanup issues

---

## PART 8: EDGE CASES FOUND VS TESTED

### Parser Rules

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Negative trim values | MessageRouter.py:120-122 | ✗ No | Low |
| Both values = 0 | MessageRouter.py:125-126 | ✓ Yes | - |
| All lines removed | MessageRouter.py:135-139 | ✗ No | Low |
| Invalid config type | MessageRouter.py:158-160 | ✗ No | Low |
| None parser | MessageRouter.py:157 | ✓ Yes | - |

---

### Keyword Matching

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Empty keywords → forward all | MessageRouter.py:88-89 | ✓ Yes | - |
| None keywords → forward all | ConfigManager.py:260-261 | ✗ No | Low |
| Case-insensitive matching | MessageRouter.py:91 | ✓ Yes | - |
| OCR text included | MessageRouter.py:82-84 | ✓ Yes | - |
| Multiple keyword matches | MessageRouter.py:91-93 | ✓ Yes | - |
| Duplicate keywords deduplicated | ConfigManager.py:289 | ✗ No | Low |

---

### OCR

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| EasyOCR not installed | OCRHandler.py:40-42 | ✓ Yes | - |
| Reader init fails | OCRHandler.py:35-36 | ✓ Partial | Low |
| OCR processing fails | OCRHandler.py:52-54 | ✓ Yes | - |
| Empty OCR result | OCRHandler.py:51 | ✓ Yes | - |
| Lazy reader initialization | OCRHandler.py:28-36 | ✓ Yes | - |

---

### RSS

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| First run → init with current time | RSSHandler.py:41-45 | ✗ No | High |
| Entry has no timestamp | RSSHandler.py:109-110 | ✗ No | Medium |
| Entry older than 2 days | RSSHandler.py:112-113 | ✗ No | Medium |
| Entry already seen | RSSHandler.py:115-116 | ✗ No | High |
| Summary > 1000 chars | RSSHandler.py:97-98 | ✓ Yes | - |
| Parse error (bozo) | RSSHandler.py:147-148 | ✗ No | High |
| HTML entities in content | RSSHandler.py:79-80 | ✓ Yes | - |

---

### Rate Limiting

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Ceiling rounding | DestinationHandler.py:59 | ✓ Yes | - |
| Multiple destinations tracked | DestinationHandler.py:18 | ✓ Yes | - |
| Expired rate limits auto-removed | DestinationHandler.py:49 | ✓ Yes | - |
| Discord 429 parse failure | DiscordHandler.py:88-90 | ✗ No | Low |
| Telegram FloodWaitError | TelegramHandler.py:396-399 | ✗ No | High |

---

### Chunking

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Text ≤ limit → single chunk | DestinationHandler.py:78-79 | ✓ Yes | - |
| Text exactly at limit | DestinationHandler.py:78-79 | ✓ Yes | - |
| Single line > limit | DestinationHandler.py:89-93 | ✓ Yes | - |
| Newline splitting | DestinationHandler.py:88 | ✓ Yes | - |
| Empty string | DestinationHandler.py:78-79 | ✓ Yes | - |
| Leading newlines stripped | DestinationHandler.py:93 | ✓ Partial | - |
| Telegram caption > 1024 with media | TelegramHandler.py:371-384 | ✗ No | **CRITICAL** |

---

### Restricted Mode

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| No media → allowed | TelegramHandler.py:219 | ✓ Yes | - |
| Photo → blocked | TelegramHandler.py:221-223 | ✓ Yes | - |
| Document without filename → blocked | TelegramHandler.py:231-237 | ✗ No | High |
| Extension matches, MIME doesn't → blocked | TelegramHandler.py:242 | ✗ No | High |
| MIME matches, extension doesn't → blocked | TelegramHandler.py:242 | ✗ No | High |

---

### Media Handling

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Media already downloaded → reuse | Watchtower.py:234 | ✗ No | Low |
| Download fails → None | TelegramHandler.py:256-258 | ✗ No | High |
| Cleanup leftover files on startup | Watchtower.py:87-101 | ✗ No | Low |
| Cleanup after message processing | Watchtower.py:213-219 | ✗ No | Medium |
| Cleanup error handling | Watchtower.py:218-219 | ✗ No | Low |

---

### Reply Context

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| Reply fetch fails → None | TelegramHandler.py:204-206 | ✗ No | Medium |
| Original text > 200 chars → truncated | TelegramHandler.py:133-135, 463-464 | ✗ No | Low |
| Media only, no caption → placeholder | TelegramHandler.py:137-138, 466-467 | ✗ No | Low |

---

### Channel Matching

| Edge Case | Location | Tested? | Risk |
|-----------|----------|---------|------|
| RSS URL as channel ID | MessageRouter.py:181-182 | ✓ Yes | - |
| Direct username/ID match | MessageRouter.py:185-186 | ✓ Yes | - |
| -100 prefix for supergroups | MessageRouter.py:189-194 | ✗ No | Low |

---

## PART 9: ERROR HANDLING PATHS FOUND VS TESTED

### Network Errors

| Error Path | Location | Tested? | Risk |
|------------|----------|---------|------|
| Discord webhook POST exception | DiscordHandler.py:77-79 | ✓ Yes | - |
| Discord webhook 500 error | DiscordHandler.py:68-74 | ✓ Yes | - |
| Discord webhook 429 rate limit | DiscordHandler.py:50-52, 65-67 | ✓ Yes | - |
| Telegram FloodWaitError | TelegramHandler.py:396-399 | ✗ No | **HIGH** |
| Telegram send exception | TelegramHandler.py:401-403 | ✗ No | **HIGH** |
| RSS feed parse error (bozo) | RSSHandler.py:147-148 | ✗ No | **HIGH** |
| RSS feed poll exception | RSSHandler.py:181-182 | ✗ No | **HIGH** |

---

### File I/O Errors

| Error Path | Location | Tested? | Risk |
|------------|----------|---------|------|
| Config file not found | ConfigManager.py:56 | ✗ No | Medium |
| Config JSON parse error | ConfigManager.py:(implied) | ✗ No | Medium |
| Keyword file not found | ConfigManager.py:224 | ✗ No | Medium |
| Keyword file invalid JSON | ConfigManager.py:229-230 | ✗ No | Medium |
| Metrics file parse error | MetricsCollector.py:34-36 | ✓ Partial | Low |
| RSS timestamp file read error | RSSHandler.py:52-53 | ✗ No | Medium |
| Media download exception | TelegramHandler.py:256-258 | ✗ No | High |
| Attachment cleanup exception | Watchtower.py:99-100 | ✗ No | Low |
| Media cleanup exception | Watchtower.py:218-219 | ✗ No | Low |

---

### Configuration Errors

| Error Path | Location | Tested? | Risk |
|------------|----------|---------|------|
| Missing API credentials | ConfigManager.py:28-29 | ✗ No | High |
| Missing env_key | ConfigManager.py:127, 138 | ✗ No | Medium |
| No valid destinations | ConfigManager.py:73 | ✗ No | Medium |
| Invalid channels format | ConfigManager.py:155-157 | ✗ No | Low |
| Invalid keywords format | ConfigManager.py:264-265 | ✗ No | Low |
| Invalid keyword file format | ConfigManager.py:232-240 | ✗ No | Medium |

---

### Business Logic Errors

| Error Path | Location | Tested? | Risk |
|------------|----------|---------|------|
| Message has no destinations | Watchtower.py:188-191 | ✓ Partial | Low |
| All destinations fail | Watchtower.py:204 | ✗ No | Medium |
| OCR reader init fails | OCRHandler.py:34-36 | ✓ Partial | Low |
| OCR extraction fails | OCRHandler.py:52-54 | ✓ Yes | - |
| Reply context fetch fails | TelegramHandler.py:204-206 | ✗ No | Medium |
| Top-level message handling exception | Watchtower.py:208-210 | ✗ No | **HIGH** |

---

### Async/Concurrency Errors

| Error Path | Location | Tested? | Risk |
|------------|----------|---------|------|
| Task cancellation | Watchtower.py:132-134 | ✗ No | Medium |
| Retry queue processing exception | MessageQueue.py:130-132 | ✗ No | **HIGH** |
| RSS feed processing exception | RSSHandler.py:181-182 | ✗ No | **HIGH** |

---

## PART 10: RECOMMENDATIONS FOR IMPROVING TEST CONFIDENCE

### PRIORITY 1: Critical Path Testing (Required for Production)

#### 1. Async Message Pipeline Integration Tests

**Target:** 90% confidence in core pipeline

**Required Tests:**
- Test complete Telegram → Discord flow (mocked network)
- Test complete RSS → Discord flow
- Test complete Telegram → Telegram flow
- Test OCR extraction → keyword matching → routing
- Test media download → restricted mode → send
- Test reply context extraction → formatting → send

**Implementation Approach:**
- Mock Telegram API with realistic message objects
- Mock Discord webhooks with various responses
- Mock feedparser with realistic RSS XML
- Use asyncio test utilities for async testing
- Verify metrics incremented correctly
- Verify cleanup runs even on errors

**Files to Create:**
- `tests/test_integration_pipeline.py` (new file)
- Add ~15 integration tests

---

#### 2. RSS Feed Polling Tests

**Target:** 90% confidence in RSS feature

**Required Tests:**
- Test `run_feed()` with mocked feedparser
- Test entry timestamp filtering (already seen, too old)
- Test first run initialization
- Test timestamp persistence across restarts
- Test parse error recovery
- Test MAX_ENTRY_AGE_DAYS filtering

**Implementation Approach:**
- Mock feedparser.parse() with realistic feed objects
- Mock file I/O for timestamp persistence
- Mock time.time() for deterministic testing
- Test poll interval timing
- Verify metrics incremented

**Files to Create:**
- `tests/test_rss_integration.py` (new file)
- Add ~10 RSS tests

---

#### 3. Retry Queue Processing Tests

**Target:** 90% confidence in retry logic

**Required Tests:**
- Test `process_queue()` background task
- Test retry success → removal from queue
- Test retry failure → exponential backoff
- Test max retries → drop message
- Test Discord retry path
- Test Telegram retry path

**Implementation Approach:**
- Mock asyncio.sleep() for fast tests
- Mock Watchtower._send_to_discord/telegram
- Verify backoff timing
- Verify queue state after each operation
- Verify metrics incremented

**Files to Create:**
- `tests/test_queue_processing.py` (new file)
- Add ~8 queue processing tests

---

#### 4. Telegram Send Operations Tests

**Target:** 90% confidence in Telegram sending

**Required Tests:**
- Test `send_copy()` basic text
- Test caption > 1024 → captionless media + text chunks
- Test message > 4096 → multiple text chunks
- Test FloodWaitError → enqueue for retry
- Test media with caption ≤ 1024 → single send

**Implementation Approach:**
- Mock TelegramClient.send_message/send_file
- Create messages with various lengths
- Verify chunking logic
- Verify FloodWaitError handling
- Verify metrics incremented

**Files to Modify:**
- `tests/test_handlers.py` (add to existing TelegramHandler tests)
- Add ~8 send operation tests

---

#### 5. Media Download Tests

**Target:** 85% confidence in media handling

**Required Tests:**
- Test `download_media()` success
- Test download failure → return None
- Test cleanup after message processing
- Test startup cleanup of leftover files

**Implementation Approach:**
- Mock TelegramClient.download_media
- Mock file system operations
- Verify cleanup on success/failure
- Verify metrics incremented

**Files to Create:**
- `tests/test_media_handling.py` (new file)
- Add ~6 media tests

---

### PRIORITY 2: Security and Edge Cases

#### 6. Restricted Mode Complete Tests

**Target:** 100% confidence in security feature

**Required Tests:**
- Test document with extension + MIME match → allowed
- Test document with extension but wrong MIME → blocked
- Test document with MIME but wrong extension → blocked
- Test document without attributes → blocked

**Files to Modify:**
- `tests/test_handlers.py` (add to TelegramHandler tests)
- Add ~5 restricted mode tests

---

#### 7. Configuration Loading Edge Cases

**Target:** 80% confidence in config validation

**Required Tests:**
- Test RSS deduplication
- Test missing env vars → skip destination
- Test invalid JSON → error
- Test multiple destinations with same channel

**Files to Modify:**
- `tests/test_core.py` (add to ConfigManager tests)
- Add ~6 config tests

---

#### 8. Error Handling Paths

**Target:** 75% confidence in error recovery

**Required Tests:**
- Test all network error scenarios
- Test all file I/O error scenarios
- Test configuration validation errors
- Test async task cancellation

**Files to Create:**
- `tests/test_error_handling.py` (new file)
- Add ~12 error handling tests

---

### PRIORITY 3: Completeness

#### 9. Missing Integration Tests

**Target:** 60% integration coverage

**Required Tests:**
- Test startup/shutdown flow
- Test metrics collection across full pipeline
- Test multiple async sources running concurrently
- Test parser removes all content → placeholder

**Files to Modify:**
- `tests/test_integration.py`
- Add ~6 integration tests

---

#### 10. Reply Context and Formatting

**Target:** 80% formatting coverage

**Required Tests:**
- Test reply context extraction from Telegram
- Test reply context formatting in Discord/Telegram
- Test OCR text formatting in Discord/Telegram
- Test defanged URL display

**Files to Modify:**
- `tests/test_handlers.py`
- Add ~6 formatting tests

---

## PART 11: TEST COVERAGE SUMMARY BY COMPONENT

| Component | Total Lines | Coverage % | Critical Gaps |
|-----------|-------------|------------|---------------|
| **MessageData** | 38 | 100% | None |
| **MetricsCollector** | 106 | 95% | reset_metric |
| **OCRHandler** | 55 | 95% | Reader init failure (minor) |
| **DestinationHandler** | 123 | 90% | None |
| **MessageRouter** | 197 | 85% | is_channel_restricted, is_ocr_enabled_for_channel |
| **DiscordHandler** | 141 | 75% | Reply context, OCR text, defanged URL display |
| **MessageQueue** | 150 | 60% | **process_queue, _retry_send (CRITICAL)** |
| **TelegramHandler** | 474 | 40% | **send_copy, caption overflow, FloodWaitError (CRITICAL)** |
| **ConfigManager** | 302 | 30% | RSS dedup, error paths, validation |
| **RSSHandler** | 189 | 30% | **run_feed, _process_entry, timestamp persistence (CRITICAL)** |
| **Watchtower** | 739 | 20% | **_handle_message, entire pipeline (CRITICAL)** |

**Overall Estimated Coverage: 55%**

**Well-Tested (≥85%):** MessageData, MetricsCollector, OCRHandler, DestinationHandler, MessageRouter
**Moderately-Tested (50-84%):** DiscordHandler, MessageQueue
**Poorly-Tested (<50%):** TelegramHandler, ConfigManager, RSSHandler, Watchtower

---

## PART 12: ROADMAP TO 90% CONFIDENCE

### Phase 1: Critical Paths (2-3 weeks)

**Goal:** Eliminate all CRITICAL gaps

1. Add async message pipeline tests (Priority 1.1)
2. Add RSS feed polling tests (Priority 1.2)
3. Add retry queue processing tests (Priority 1.3)
4. Add Telegram send operations tests (Priority 1.4)
5. Add media download tests (Priority 1.5)

**Expected Coverage After Phase 1: 75%**

---

### Phase 2: Security and Error Handling (1-2 weeks)

**Goal:** Eliminate security risks and error handling gaps

6. Complete restricted mode tests (Priority 2.6)
7. Add configuration loading edge case tests (Priority 2.7)
8. Add comprehensive error handling tests (Priority 2.8)

**Expected Coverage After Phase 2: 82%**

---

### Phase 3: Completeness (1 week)

**Goal:** Fill remaining gaps for production readiness

9. Add missing integration tests (Priority 3.9)
10. Add reply context and formatting tests (Priority 3.10)

**Expected Coverage After Phase 3: 90%**

---

### Phase 4: Mutation Testing (Optional, 1 week)

**Goal:** Verify test quality

11. Install and configure mutmut
12. Run mutation testing on critical modules
13. Add tests to kill surviving mutants

**Expected Mutation Score: 75-80%**

---

## PART 13: CONCLUSION

The Watchtower test suite provides **moderate confidence (65%)** for production use. Core utilities are well-tested, but critical async operations, RSS polling, retry queue processing, and Telegram send operations have insufficient coverage.

**Strengths:**
- Well-organized test structure (core, handlers, integration)
- Good use of mocking for network dependencies
- Comprehensive unit tests for utilities
- Dependency injection enables testability
- High coverage for MessageData, MetricsCollector, OCRHandler

**Weaknesses:**
- Minimal async testing (0% for critical paths)
- RSS handler almost untested (30%, polling untested)
- Critical Telegram operations untested (send_copy, caption overflow)
- End-to-end flows under-tested (35%)
- Error paths under-tested
- Media handling untested (0%)

**To achieve 90% production confidence:**
1. **Phase 1 (Critical):** Add async pipeline, RSS polling, retry queue, Telegram send, media download tests
2. **Phase 2 (Security):** Complete restricted mode, config validation, error handling tests
3. **Phase 3 (Polish):** Add integration tests, formatting tests

**Estimated Effort:**
- Phase 1: 2-3 weeks (40-60 new tests)
- Phase 2: 1-2 weeks (23 new tests)
- Phase 3: 1 week (12 new tests)
- **Total: 4-6 weeks, ~75-95 new tests**

**Current Risk Assessment:**
- **High Risk:** Async pipeline failures, RSS failures, retry queue failures, Telegram content loss
- **Medium Risk:** Configuration errors, media download failures, restricted mode bypass
- **Low Risk:** Formatting issues, minor edge cases

**Recommendation:** Prioritize Phase 1 (critical paths) before production deployment. Phase 2 should follow shortly after. Phase 3 can be done incrementally.

---

## APPENDIX: QUICK REFERENCE

### Test Execution

```bash
# Run all tests
python -m unittest discover -v tests/

# Run with coverage
coverage run -m unittest discover tests/
coverage report
coverage html

# Run specific test file
python -m unittest tests.test_core -v

# Run specific test class
python -m unittest tests.test_core.TestMessageRouter -v

# Run specific test method
python -m unittest tests.test_core.TestMessageRouter.test_match_keywords_case_insensitive -v
```

### Coverage Analysis

```bash
# Generate coverage report
coverage run -m unittest discover tests/
coverage report --show-missing

# Generate HTML report
coverage html
# Open htmlcov/index.html in browser

# Generate XML for CI
coverage xml
```

### Key Files

- **Source Code:** `src/` (11 files, ~2,514 lines)
- **Tests:** `tests/` (3 files, 82 tests)
- **Config:** `config/config.json`
- **Keywords:** `config/kw-*.json`
- **Metrics:** `tmp/metrics.json`
- **RSS Timestamps:** `tmp/rsslog/*.txt`
- **Media Downloads:** `tmp/attachments/*`

---

**Report Generated:** 2025-11-04
**Analysis Tool:** Manual code review + test execution
**Next Review:** After Phase 1 completion
