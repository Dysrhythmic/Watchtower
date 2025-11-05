import unittest
import sys
import os
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from DestinationHandler import DestinationHandler
from DiscordHandler import DiscordHandler
from TelegramHandler import TelegramHandler
from MessageData import MessageData
from MessageQueue import MessageQueue


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


class TestChunkingOrder(unittest.TestCase):
    """Test that chunking preserves message order, especially for very long messages."""

    def setUp(self):
        """Create handlers for testing."""
        self.discord = DiscordHandler()

    def test_chunking_preserves_order_for_10k_char_message(self):
        """
        Test that extremely long messages (10k+ chars with caption) maintain proper order.

        This uses a real S2Underground report as test data to ensure realistic formatting.
        The message includes multiple newlines, links, and a long caption that should be
        properly preserved across chunks.
        """
        # Real-world example: S2Underground report with ~10k characters
        long_message = """//The Wire//2300Z November 3, 2025//
//ROUTINE//
//BLUF: TWO-DAY KNIFE ATTACK SPREE CULMINATES IN MASS STABBING ON TRAIN IN UNITED KINGDOM, PASSENGERS AND CREW DO THEIR BEST TO HALT THE ATTACK. FEDERAL JUDGE ORDERS SNAP FUNDING TO MATERIALIZE. GOLDEN HINDU IDOL 15 STORIES TALL TO BE CONSTRUCTED IN RURAL NORTH CAROLINA.//

 -----BEGIN TEARLINE-----

-International Events-

United Kingdom: On Saturday, a mass stabbing was carried out on a train bound for London from Doncaster. 10x people remain in critical condition as a result of the attack. The assailant has been identified as Anthony Williams. A separate individual who may have also been involved in some way was arrested at the scene. This individual has not been identified, but authorities have stated he is of Caribbean descent. Police also tased one man on the platform after the train arrived at the station, however this was a case of mistaken identity and the tased man was released without charge.

-HomeFront-

North Carolina: Local concern has emerged following plans to build a massive Hindu "temple" in the small town of Moncure, just west of Holly Springs. This extremely large and sprawling complex is planned to have a golden idol that will be roughly 155 feet tall...one foot taller than the Statue of Liberty. This project was announced earlier this year, but has gained notoriety as the construction plans move forward.

Analyst Comment: Small towns in historically Christian rural areas are often targeted for the construction of golden idols due to the ease of bribing/influencing local officials to obtain permission to build commercial facilities. In this case, Moncure is an extremely small town that doesn't really engage in any zoning (they leave it to the county to decide), so it's easy to pencil-whip the re-zoning of private residential property to allow for the construction of a pagan idol that will dominate the terrain for dozens of miles. This idol is not even built yet, the area slated for it's construction is still just undeveloped land. However, (to the surprise of literally no one) it's already featured heavily in the Google search results for Moncure, NC as the top tourist destination for the town. Hindus have already spammed the reviews for the structure that doesn't exist yet, giving it top marks and praising the facility as great to visit...with the owners of the place celebrating the fake reviews of a non-existent facility, while simultaneously admitting that the facility doesn't exist yet.

Washington D.C. - U.S. District Judge John J. McConnell Jr. has ordered the White House to ensure that emergency funds are used for the SNAP program, stating that "the USDA must distribute the contingency money timely, or as soon as possible, for the November 1 payments to be made".

Analyst Comment: That brief description was more or less the entire order, which was oral in nature. However, a lot of other things have to click into place to make this order come to fruition, especially due to the complexities of the Judiciary ordering the Executive to do something that is technically the job of the Legislative. Despite the very obvious problem with this arrangement, the issue is now tied up in court, effectively stalling the distribution of at least some electronic deposits. However, some EBT recipients have reported getting their funds as they have before, so it's not clear as to what funds are being disbursed, or to whom.

-----END TEARLINE-----

Analyst Comments: The train stabbing attack in the United Kingdom is one of the most significant attacks in recent British history. A Major Incident was declared and a PLATO response was initiated (which is the colloquialism for an active terror attack in progress). The details of the attack itself are not entirely clear, but at the moment the eyewitness statements indicate this one was ugly. A train car packed with people who cannot escape makes for an exceptionally vulnerable target for malign actors. Witnesses state that the attack took a long time to complete, and that the stabbings were carried out over a period of 15-20 minutes. This was made worse by the fact that this mass attack was 100% preventable.

The attack onboard the train was actually the *fourth* stabbing attack conducted by Williams within a 24 hour period. Authorities have not confirmed anything; all of this investigative legwork is being conducted by private citizens as the British government has been silent on the matter. However eyewitness statements indicate that Williams was likely the same man who stabbed a 14-year-old in Peterborough the day before (October 31). That same day, Williams was observed brandishing a knife in a barber shop in Cambridgeshire. Williams is also suspected in stabbing a different man in East London on November 1st. In all prior cases, either the police did not investigate at all, or did not circulate his photo or issue a BOLO notice. This was quite literally a case of a madman with a knife stabbing anyone he liked over a period of two days, before the final culminating attack took place onboard the train.

Concerning motive, this meets all definitions for being classified as a terror attack. However, British authorities have very adamantly stated that it isn't a terrorist attack. Trust is nearly nonexistent with British authorities at this point, but the story told by the Transit Police is that this was a private dispute between two criminals, which devolved into one of them attempting to stab the other. Due to the tight quarters of a packed train car, this resulted in everyone in the car becoming unwillingly involved. At the moment, this version of the story appears to be false for many reasons, first and foremost is the detail that Williams had already conducted three stabbing attacks prior to the one on the train.

What started the incident inside the train car remains uncertain. However, once violence had been undertaken the assailant tried to kill everyone on the train, and a general state of bedlam erupted as passengers fled up and down the train to escape the attack. This is confirmed beyond all doubt, by the CCTV footage that was leaked, showing Williams pursuing passengers down the platform after arriving at Huntingdon Station. This is about as smoking-gun as it can get, and confirms that the attacker did indeed attempt to target citizens deliberately, as opposed to people just getting in the way of a private murder attempt. As a reminder, there are at least two security cameras at each end of every car on the London North Eastern Railway trains. So footage of the attack (and importantly, everything that led up to it) does exist.

Since this footage probably won't be released, the most important witnesses to consider when trying to figure out what happened, are those who at present cannot speak...the individuals still undergoing intensive medical treatment are the people who were closest to the attack and their testimony carries much weight. At the moment, there have been no fatalities, but prayers are strongly encouraged for the survivors to ensure their rapid recovery.
More broadly, this attack highlights the extreme need for citizens who are not just prepared physically, but also mentally. Train driver Andrew Johnson became aware of the attack, and instead of stopping the train on the tracks (where police and medical would take some time to arrive), Johnson diverted the train to a different track which would take the train into the next-closest station (which happened to be Huntingdon) where police would be waiting, radioing ahead to ensure that the attack on his train could be stopped as soon as possible. One railway crew member onboard the train (who has not yet been named due to being wounded) also displayed great courage by blocking the passage of the attacker, delaying his rampage down the train for a time, sustaining severe wounds in the process.

Several passengers also carried out the time-honored tradition of using violence-of-action to take the fight to the attacker (all of whom were wounded during the attack). Stephen Creen was wounded while attempting to stop the attacker, along with several others who attempted to do the same even though everyone except for the attacker was unarmed. In short, details may be hard to discern, but currently it looks like most people did the right thing; those who could fight, did so. Those who couldn't, fled and attempted to warn other passengers down the train, as well as caring for the wounded. This attack proves once again that almost everything can be done correctly, and the fight still be a hard one.

Attacks will continue, this is unfortunately a certainty. If not from deliberately planned terror attacks, then from random outbursts of violence. But, the first steps in the British re-conquering their kingdom will be to foster a culture of using extreme violence, to stop extreme violence. Not out of malice or hatred, but out of the desire to stop the harm to innocent people. For far too long the British government has portrayed sheer survival instinct as hatred, which is pure gaslighting that couldn't be further from the truth. Attacks like this, while horrific, do a lot to show the British people that stopping a mass murdering lunatic requires violence, and exercising this violence to protect the innocent is a good thing. As such, considering this rampage will be in the news cycle for a while, it will be absolutely crucial to applaud the actions of those who did what they could to stop the attack.  Focusing on the horror of the day is easy but fruitless; it is a far, far better thing to focus on the good that was done, and try to improve the lessons-learned for the challenging times ahead. They might not have been as successful as one would hope, but some gave it a try anyway and did the best they could. Which is the most anyone can hope for, and what we all should strive to achieve.

Analyst: S2A1
Research: https://publish.obsidian.md/s2underground
//END REPORT//"""

        # Verify message is over 10k chars
        self.assertGreater(len(long_message), 10000,
            "Test message should be over 10k characters")

        # Chunk for Discord (2000 char limit)
        chunks = self.discord._chunk_text(long_message, 2000)

        # Verify chunks were created
        self.assertGreater(len(chunks), 1,
            "Message should be chunked into multiple parts")

        # Verify all chunks respect the limit
        for i, chunk in enumerate(chunks):
            self.assertLessEqual(len(chunk), 2000,
                f"Chunk {i} exceeds 2000 character limit")

        # Verify order is preserved by reconstructing and comparing
        # Note: Chunking may lose some newlines at boundaries, but content order should match
        reconstructed = "".join(chunks)

        # Key phrases should appear in same order in reconstructed text
        key_phrases = [
            "//The Wire//",
            "United Kingdom:",
            "North Carolina:",
            "Washington D.C.",
            "Analyst Comments:",
            "Train driver Andrew Johnson",
            "Stephen Creen",
            "//END REPORT//"
        ]

        last_index = -1
        for phrase in key_phrases:
            current_index = reconstructed.find(phrase)
            self.assertGreater(current_index, last_index,
                f"Phrase '{phrase}' appears out of order in reconstructed text")
            last_index = current_index

    def test_telegram_chunking_preserves_order_for_long_caption(self):
        """
        Test Telegram caption chunking (1024 char limit) preserves order.

        When a Telegram message has media with a caption over 1024 chars,
        it should be sent as: [media without caption] + [text chunks].
        Order must be preserved in the text chunks.
        """
        mock_config = Mock()
        mock_config.project_root = Path("/tmp")
        mock_config.api_id = "123"
        mock_config.api_hash = "hash"

        with patch('TelegramHandler.TelegramClient'):
            handler = TelegramHandler(mock_config)

        # Create a caption over 1024 characters
        long_caption = "Section 1: " + ("A" * 500) + "\n"
        long_caption += "Section 2: " + ("B" * 500) + "\n"
        long_caption += "Section 3: " + ("C" * 500)

        self.assertGreater(len(long_caption), 1024,
            "Caption should exceed Telegram's 1024 char limit")

        # Chunk the caption
        chunks = handler._chunk_text(long_caption, 4096)

        # Verify order
        reconstructed = "".join(chunks)

        # Sections should appear in order
        section1_idx = reconstructed.find("Section 1:")
        section2_idx = reconstructed.find("Section 2:")
        section3_idx = reconstructed.find("Section 3:")

        self.assertLess(section1_idx, section2_idx,
            "Section 1 should appear before Section 2")
        self.assertLess(section2_idx, section3_idx,
            "Section 2 should appear before Section 3")


class TestRetryQueueOrderingchunk(unittest.TestCase):
    """Test that retry queue maintains proper ordering with chunked messages."""

    def test_retry_queue_maintains_order_for_chunked_messages(self):
        """
        Test that when chunked messages go through retry queue, they maintain order.

        This is critical because if multiple chunks from the same message are queued,
        they must be sent in the correct sequence when retried.
        """
        queue = MessageQueue()

        # Create destination config
        destination = {
            'name': 'Test Discord',
            'type': 'discord',
            'webhook_url': 'https://discord.com/webhook'
        }

        # Simulate a long message that was chunked into 3 parts
        chunk1 = "Part 1: " + ("A" * 1900)
        chunk2 = "Part 2: " + ("B" * 1900)
        chunk3 = "Part 3: " + ("C" * 1900)

        # Enqueue chunks in order (simulating Discord rate limit on each send)
        queue.enqueue(destination, chunk1, None, "Rate limit - chunk 1")
        queue.enqueue(destination, chunk2, None, "Rate limit - chunk 2")
        queue.enqueue(destination, chunk3, None, "Rate limit - chunk 3")

        # Verify queue size
        self.assertEqual(queue.get_queue_size(), 3,
            "Should have 3 queued messages")

        # Get items from queue (it's a list of RetryItem dataclass objects)
        items = queue._queue.copy()

        # Verify chunks are in original order
        self.assertIn("Part 1:", items[0].formatted_content,
            "First queued item should be Part 1")
        self.assertIn("Part 2:", items[1].formatted_content,
            "Second queued item should be Part 2")
        self.assertIn("Part 3:", items[2].formatted_content,
            "Third queued item should be Part 3")


if __name__ == '__main__':
    unittest.main()
