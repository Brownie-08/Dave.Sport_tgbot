# Web App Debugging Guide

## Current Situation
Your Web App is showing "Failed to load. Try again." with 403 Forbidden errors.

## ✅ What I've Fixed
1. **Better error display** - Now shows specific error messages
2. **Console logging** - Added debug logs to help identify the issue
3. **Error handling** - Properly catches `err.detail` from FastAPI

## 🔍 Next Steps to Diagnose

### Step 1: Check Browser Console
1. Open the Web App in Telegram
2. If you're testing via ngrok in a browser:
   - Press `F12` to open DevTools
   - Go to **Console** tab
   - Look for error messages
   - You should see logs like:
     - "Attempting auth with initData length: XXX"
     - "Auth failed: XXXX"

3. Check what the error message says:
   - `missing_hash` → initData doesn't have a hash
   - `invalid_hash` → Bot token mismatch
   - `init_data_expired` → Session older than 24 hours
   - `missing_init_data` → Telegram Web App not initialized

### Step 2: Verify Bot Configuration

Check if the Web App URL is configured in @BotFather:
1. Go to @BotFather in Telegram
2. Send `/mybots`
3. Select @Davesportbot
4. Choose "Bot Settings" → "Menu Button"
5. Make sure your ngrok URL is set (e.g., `https://xxxx.ngrok.io`)

### Step 3: Test Authentication Manually

Run the test script with actual initData:
```powershell
# Get initData from browser console
# In Web App, open F12 Console and type:
# Telegram.WebApp.initData

# Then test it:
python test_webapp_auth.py "query_id=...&user=...&auth_date=...&hash=..."
```

### Step 4: Check Bot Token

Make sure the `BOT_TOKEN` in your `.env` file matches the bot you're testing with:
```powershell
# Check your .env file
Get-Content .env | Select-String "BOT_TOKEN"
```

## 🛠️ Common Fixes

### Issue: "missing_init_data"
**Cause:** Web App not opened from Telegram  
**Fix:** Open the app by clicking the menu button in your bot chat

### Issue: "invalid_hash"
**Cause:** Wrong bot token or tampered data  
**Fix:** 
1. Verify `BOT_TOKEN` in `.env` matches your bot
2. Make sure you're testing with the correct bot
3. Try revoking and getting a new token from @BotFather

### Issue: "init_data_expired"
**Cause:** initData older than 24 hours  
**Fix:** Close and reopen the Web App fresh

### Issue: CORS errors in browser
**Cause:** ngrok/CORS configuration  
**Fix:** Already handled - CORS is set to allow all origins

## 📋 Testing Checklist

- [ ] Bot is running (`python main.py`)
- [ ] No 409 conflicts (only one instance)
- [ ] ngrok tunnel is active
- [ ] Web App URL is set in @BotFather
- [ ] `.env` has correct `BOT_TOKEN`
- [ ] Opening app from Telegram (not directly in browser)

## 🎯 Expected Behavior

When working correctly, you should see:
1. Web App opens in Telegram
2. Console shows: "Attempting auth with initData length: 200-300"
3. Console shows: "Auth successful for user: YourUsername"
4. Dashboard loads with your profile

## 🆘 Still Not Working?

If you've tried everything above:
1. Check the bot terminal for logs showing the auth attempt
2. The backend now logs:
   - "Auth attempt - initData length: XXX"
   - "Auth failed: XXXX" (with specific error)
3. Share these logs to diagnose further

## 💡 Pro Tip

You can temporarily disable auth validation for testing by modifying the backend, but **don't use this in production**:

```python
# In backend/app.py, temporarily change _telegram_auth:
def _telegram_auth(payload: TelegramAuthPayload):
    # TESTING ONLY - REMOVE IN PRODUCTION
    user_id = 123456789  # Your Telegram user ID
    username = "testuser"
    service.ensure_user(user_id, username)
    role = service.get_user_role(user_id)
    token = auth_utils.create_jwt({
        "sub": user_id, 
        "username": username, 
        "role": role
    })
    return {"token": token, "user": {"id": user_id, "username": username, "role": role}}
```

This bypasses auth validation so you can test if the rest of the app works.
