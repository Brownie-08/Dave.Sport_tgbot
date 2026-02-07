#!/usr/bin/env python3
"""
Helper script to stop running bot instances.
This reads the PID from bot.lock and terminates the process.
"""
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

LOCK_FILE = Path("bot.lock")

def stop_bot():
    """Stop the running bot instance."""
    if not LOCK_FILE.exists():
        logging.info("No lock file found. Bot may not be running.")
        return
    
    try:
        with open(LOCK_FILE, 'r') as f:
            pid = int(f.read().strip())
        
        logging.info(f"Found bot instance with PID: {pid}")
        
        # Try to terminate the process
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_TERMINATE = 0x0001
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            
            if handle:
                if kernel32.TerminateProcess(handle, 0):
                    logging.info(f"Successfully terminated process {pid}")
                    kernel32.CloseHandle(handle)
                    
                    # Remove lock file
                    if LOCK_FILE.exists():
                        LOCK_FILE.unlink()
                        logging.info("Lock file removed")
                else:
                    logging.error(f"Failed to terminate process {pid}")
                    kernel32.CloseHandle(handle)
            else:
                logging.warning(f"Process {pid} not found or already terminated")
                # Remove stale lock file
                if LOCK_FILE.exists():
                    LOCK_FILE.unlink()
                    logging.info("Removed stale lock file")
        except Exception as e:
            logging.error(f"Error terminating process: {e}")
            logging.info("You may need to manually stop the process")
    
    except (ValueError, FileNotFoundError) as e:
        logging.error(f"Invalid lock file: {e}")
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
            logging.info("Removed invalid lock file")

if __name__ == "__main__":
    stop_bot()
