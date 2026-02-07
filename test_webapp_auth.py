#!/usr/bin/env python3
"""
Test script for debugging Telegram Web App authentication.
This helps diagnose 403 Forbidden errors on /api/auth/telegram
"""
import sys
import json
from backend import auth as auth_utils
import config

def test_init_data(init_data_string: str):
    """Test if initData can be verified."""
    print("="*60)
    print("Testing Telegram Web App Authentication")
    print("="*60)
    
    print(f"\n1. initData length: {len(init_data_string)} characters")
    print(f"2. initData preview: {init_data_string[:100]}...")
    
    if not config.BOT_TOKEN:
        print("\n❌ ERROR: BOT_TOKEN not found in config")
        return False
    
    print(f"\n3. Bot token configured: {config.BOT_TOKEN[:20]}...")
    
    try:
        print("\n4. Attempting to verify initData...")
        parsed = auth_utils.verify_init_data(init_data_string, config.BOT_TOKEN)
        print("✅ SUCCESS: initData verification passed!")
        
        user = parsed.get("user", {})
        print(f"\n5. Extracted user data:")
        print(f"   - User ID: {user.get('id')}")
        print(f"   - Username: {user.get('username')}")
        print(f"   - First name: {user.get('first_name')}")
        print(f"   - Auth date: {parsed.get('auth_date')}")
        
        return True
    
    except ValueError as e:
        print(f"\n❌ FAILURE: {e}")
        print("\nCommon causes:")
        if "missing_hash" in str(e):
            print("  - initData doesn't contain a hash parameter")
            print("  - Web App might not be properly initialized")
        elif "invalid_hash" in str(e):
            print("  - The hash doesn't match (wrong bot token or tampered data)")
            print("  - Make sure BOT_TOKEN in .env matches the bot you're testing with")
            print("  - NOTE: Fixed the secret key calculation to use HMAC-SHA256 with 'WebAppData'")
        elif "init_data_expired" in str(e):
            print("  - initData is older than 24 hours")
            print("  - Try opening the Web App fresh from Telegram")
        
        return False

def main():
    print("\n" + "="*60)
    print("Telegram Web App Auth Tester")
    print("="*60)
    
    if len(sys.argv) > 1:
        # Test with provided initData
        init_data = sys.argv[1]
        test_init_data(init_data)
    else:
        print("\nUsage:")
        print("  python test_webapp_auth.py \"<initData_string>\"")
        print("\nHow to get initData:")
        print("  1. Open your bot's Web App in Telegram")
        print("  2. Open browser DevTools (F12)")
        print("  3. Go to Console tab")
        print("  4. Type: Telegram.WebApp.initData")
        print("  5. Copy the output and paste it as argument to this script")
        print("\nExample:")
        print("  python test_webapp_auth.py \"query_id=...&user=...&auth_date=...&hash=...\"")
        
        print("\n" + "="*60)
        print("Alternative: Test current bot configuration")
        print("="*60)
        
        if config.BOT_TOKEN:
            print(f"\n✅ BOT_TOKEN is configured")
            print(f"   Token preview: {config.BOT_TOKEN[:20]}...{config.BOT_TOKEN[-10:]}")
            print("\nBot token looks valid. The issue is likely:")
            print("  1. Telegram Web App not initialized properly")
            print("  2. initData not being sent from frontend")
            print("  3. CORS or ngrok configuration issue")
        else:
            print("\n❌ BOT_TOKEN is not configured")
            print("   Please check your .env file")

if __name__ == "__main__":
    main()
