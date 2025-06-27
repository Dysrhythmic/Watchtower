# Telecord

<img src="./telecord.png" alt="Telecord Logo" width="200" height="200" />

A simple Python app to forward messages from Telegram channels to Discord channels using Telethon and Discord webhooks.

## Features
- Forwards the latest message from each configured Telegram channel on startup
- Forwards all new messages in real time
- Automatically splits long messages into 2000-character chunks for Discord
- Multiple webhooks with channel-specific routing
- Keyword filtering per channel per webhook for flexible message routing based on content

## Requirements
- Python 3.8+
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- Discord webhook URL(s) (edit channel -> integrations -> webhooks)

## Setup
1. **Clone or download this repository**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Create a `.env` file** in the project directory based on the provided `config_example.txt` file

4. **Optionally customize `webhook_config.json`** if you wish to use more advanced message routing than the default. See `config_example.txt` for more details.

5. **Run the bot:**
   ```bash
   python telecord.py
   ```
   - On first run, you will be prompted to log in to Telegram (phone number and code).
   - The session will be saved in `telecord_session.session` for future runs.

## How it works
- On startup, posts the most recent message from each channel to the appropriate Discord webhook(s)
- Listens for new messages in all channels and posts them to the configured webhook(s) in real time
- If a message is longer than 2000 characters, it is split into multiple Discord messages
- Messages are only sent to the specified webhook(s) if they contain specified keywords (case-insensitive)

## Keyword Filtering
- Keywords are case-insensitive
- If no keywords are specified for a channel, all messages from that channel are sent
- If keywords are specified, only messages containing at least one keyword are sent
- The same channel can have different keyword filters for different webhooks

## Security
- Keep your `.env` and `telecord_session.session` files private! They contain sensitive credentials.

## Troubleshooting
- If you change your Telegram account or channels, delete `telecord_session.session` and restart the bot.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the logs for errors if messages are not being forwarded.
- Verify that your Discord webhook URLs are correct and the webhooks are active.
- Ensure channel IDs in your JSON config match the actual Telegram channel identifiers.
