import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler


class TestDestinationHandler(unittest.TestCase):
    """Test DestinationHandler base class."""

    def setUp(self):
        """Create a concrete implementation for testing."""
        class ConcreteHandler(DestinationHandler):
            def _get_rate_limit_key(self, destination_identifier):
                return str(destination_identifier)
            def send_message(self, content, destination_identifier, media_path=None):
                return True
            def format_message(self, message_data, destination):
                return "formatted"

        self.handler = ConcreteHandler()

    def test_rate_limit_ceiling_rounding(self):
        """Test that retry_after is ceiling rounded."""
        import time
        before = time.time()
        self.handler._store_rate_limit("test_dest", 5.2)
        # Should round 5.2 → 6 seconds
        expires_at = self.handler._rate_limits["test_dest"]
        self.assertGreaterEqual(expires_at, before + 5.9)  # Allow small timing variance
        self.assertLess(expires_at, before + 6.2)

    def test_chunk_text_under_limit(self):
        """Test chunking text under max length returns single chunk."""
        text = "Short text"
        chunks = self.handler._chunk_text(text, 2000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_chunk_text_over_limit(self):
        """Test chunking long text splits at newlines."""
        text = ("Line 1\n" * 100) + "Line 2\n" * 100
        chunks = self.handler._chunk_text(text, 100)
        self.assertGreater(len(chunks), 1)
        # Verify no chunk exceeds limit
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 100)

    def test_chunk_text_exact_limit(self):
        """Test edge case: text exactly at limit."""
        text = "x" * 2000
        chunks = self.handler._chunk_text(text, 2000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_rate_limit_multiple_destinations(self):
        """Test rate limiting tracks multiple destinations separately."""
        import time
        self.handler._store_rate_limit("dest1", 5.0)
        self.handler._store_rate_limit("dest2", 10.0)

        self.assertIn("dest1", self.handler._rate_limits)
        self.assertIn("dest2", self.handler._rate_limits)
        self.assertNotEqual(self.handler._rate_limits["dest1"],
                           self.handler._rate_limits["dest2"])

    def test_rate_limit_expiry_check(self):
        """Test rate limit expiry checking."""
        import time
        # Set rate limit that expires in the past
        self.handler._rate_limits["expired"] = time.time() - 10

        # Should not be rate limited
        result = self.handler._check_and_wait_for_rate_limit("expired")
        self.assertIsNone(result)

    def test_chunk_text_preserves_newlines(self):
        """Test chunking preserves newline boundaries when possible."""
        text = "Line 1\n" + ("a" * 2000) + "\nLine 3"
        chunks = self.handler._chunk_text(text, 2000)

        # Should create multiple chunks
        self.assertGreater(len(chunks), 1)
        # Each chunk should respect max length
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 2000)

    def test_chunk_text_empty_string(self):
        """Test chunking empty string."""
        chunks = self.handler._chunk_text("", 2000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], "")

    def test_chunk_text_single_long_line(self):
        """Test chunking single line longer than limit."""
        text = "a" * 3000
        chunks = self.handler._chunk_text(text, 2000)
        self.assertGreater(len(chunks), 1)
        # First chunk should be exactly 2000
        self.assertEqual(len(chunks[0]), 2000)
        # Second chunk should be 1000
        self.assertEqual(len(chunks[1]), 1000)


if __name__ == '__main__':
    unittest.main()
