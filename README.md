# Telecord

<img src="./telecord.png" alt="Telecord Logo" width="200" height="200" />

A simple Python app to forward messages from Telegram channels to a Discord channel using Telethon and Discord webhooks.

## Features
- Forwards the latest message from each configured Telegram channel on startup
- Forwards all new messages in real time
- Automatically splits long messages into 2000-character chunks for Discord

## Requirements
- Python 3.8+
- Telegram API credentials ([get them here](https://my.telegram.org/apps))
- Discord webhook URL

## Setup
1. **Clone or download this repository**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Create a `.env` file** in the project directory with the following content:
   ```env
   TELEGRAM_API_ID=your_telegram_api_id
   TELEGRAM_API_HASH=your_telegram_api_hash
   TELEGRAM_CHANNEL_ID=channel1,channel2
   DISCORD_WEBHOOK_URL=your_discord_webhook_url
   ```
   - For public channels, use the username (without @)
   - For private channels, use the numeric ID
   - You can use a comma-separated list for multiple channels

4. **Run the bot:**
   ```bash
   python telecord.py
   ```
   - On first run, you will be prompted to log in to Telegram (phone number and code)
   - The session will be saved in `telecord_session.session` for future runs

## How it works
- On startup, posts the most recent message from each channel to Discord
- Listens for new messages in all channels and posts them to Discord in real time
- If a message is longer than 2000 characters, it is split into multiple Discord messages

## Security
- Keep your `.env` and `telecord_session.session` files private! They contain sensitive credentials.

## Troubleshooting
- If you change your Telegram account or channels, delete `telecord_session.session` and restart the bot.
- Make sure your Telegram account can access all the channels you want to monitor.
- Check the logs for errors if messages are not being forwarded.