# Bot Instance Management

## Problem
Telegram bots can only have one active connection at a time. Running multiple instances of the same bot simultaneously causes a `409 Conflict` error: "terminated by other getUpdates request".

## Solution
The bot now uses a lockfile mechanism (`bot.lock`) to ensure only one instance runs at a time.

## How It Works

### Starting the Bot
When you run `python main.py`, the bot:
1. Checks if a `bot.lock` file exists
2. If it exists, validates the PID inside is still running
3. If another instance is running, exits with an error message
4. If the lock is stale (process no longer exists), removes it
5. Creates a new lock file with the current process PID
6. Runs normally

### Stopping the Bot
The lock file is automatically removed when:
- The bot exits normally (Ctrl+C)
- The process terminates
- Using the `stop_bot.py` helper script

## Usage

### Start the bot
```powershell
python main.py
```

### Stop a running instance
```powershell
python stop_bot.py
```

### Manual cleanup (if needed)
If the bot crashes without cleaning up:
```powershell
# Delete the lock file manually
Remove-Item bot.lock
```

## Troubleshooting

### "Another bot instance is already running"
This means the bot is already running. You have two options:
1. **Stop the existing instance first:**
   ```powershell
   python stop_bot.py
   ```
2. **Find and kill the process manually:**
   ```powershell
   # Find Python processes
   Get-Process python
   
   # Stop by PID (replace 1234 with actual PID)
   Stop-Process -Id 1234
   ```

### Stale lock file
If you're certain no bot is running but still get the error:
```powershell
Remove-Item bot.lock
```

### Multiple instances still connecting (EXTERNAL INSTANCE)
If you still see conflict errors after implementing this fix, the bot is running **somewhere else**:

#### Finding the external instance:
1. **Check cloud deployments:**
   - Heroku: `heroku ps` or check dashboard
   - Railway: Check your Railway dashboard
   - Render: Check your Render dashboard
   - VPS/Server: SSH and check `ps aux | grep python`

2. **Check development environments:**
   - Replit: Check running repls
   - Gitpod: Check workspaces
   - GitHub Codespaces: Check active codespaces

3. **Check other machines:**
   - Work computer
   - Laptop
   - Lab computer
   - Friend's machine

#### Immediate solution (Emergency Stop):
If you can't find the instance, you can **temporarily change your bot token**:
1. Go to [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/mybots`
3. Select your bot
4. Choose "API Token" → "Revoke current token"
5. Update the token in your `.env` file
6. Restart your bot

⚠️ **Warning:** This will stop ALL instances immediately, but you'll need to update the token everywhere.

## Technical Details

- **Lock file location:** `bot.lock` in the project root
- **Lock file content:** Process ID (PID) of the running bot
- **Process validation:** Uses Windows API (`ctypes.windll.kernel32`) to verify process existence
- **Cleanup:** Registered with `atexit` for automatic cleanup on normal exit
- **Signal handling:** Handles SIGINT and SIGTERM for clean shutdown
