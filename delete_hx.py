import os
import sqlite3
import time
from pathlib import Path
import sys
import shutil
import subprocess

class BrowserHistoryCleaner:
    def __init__(self):
        self.home = Path.home()
        self.browsers_cleaned = []
        self.errors = []
        self.entries_removed = 0
        self.confirm_deletion = True  # Require confirmation before deleting

    def clean_safari_history(self):
        """Clean Safari browsing history"""
        print("\n=== Cleaning Safari History ===")
        cleaned_count = 0

        # Safari history databases
        history_paths = [
            self.home / "Library/Safari/History.db",
            self.home / "Library/Safari/HistoryIndex.sk",
            self.home / "Library/Safari/TopSites.plist"
        ]

        for path in history_paths:
            if not path.exists():
                continue

            if path.suffix == '.db':
                try:
                    # Create a backup before modification
                    backup_path = path.with_suffix(f"{path.suffix}.bak")
                    shutil.copy2(path, backup_path)

                    # Connect to the database
                    conn = sqlite3.connect(str(path))
                    cursor = conn.cursor()

                    if path.name == "History.db":
                        # Check if the history_items table exists
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='history_items';")
                        if cursor.fetchone():
                            # Count before deletion
                            cursor.execute("SELECT COUNT(*) FROM history_items")
                            count_before = cursor.fetchone()[0]

                            # Delete history items
                            cursor.execute("DELETE FROM history_items")

                            # Delete from history_visits
                            cursor.execute("DELETE FROM history_visits")

                            # Vacuum the database
                            cursor.execute("VACUUM")

                            conn.commit()
                            cleaned_count += count_before

                    conn.close()
                    print(f"Cleaned Safari history database: {path.name}")
                except Exception as e:
                    self.errors.append(f"Safari: Error cleaning {path.name}: {str(e)}")
            else:
                try:
                    # Just remove non-database history files and let Safari recreate them
                    os.remove(path)
                    cleaned_count += 1
                    print(f"Removed Safari history file: {path.name}")
                except Exception as e:
                    self.errors.append(f"Safari: Error removing {path.name}: {str(e)}")

        # Try to use AppleScript to clear history as well
        try:
            print("Clearing Safari history via AppleScript...")
            script = '''
            tell application "Safari"
                if it is running then
                    tell application "System Events" to tell process "Safari"
                        click menu item "Clear History..." of menu "History" of menu bar 1
                        delay 1
                        click pop up button 1 of sheet 1 of window 1
                        delay 0.5
                        click menu item "all history" of menu 1 of pop up button 1 of sheet 1 of window 1
                        delay 0.5
                        click button "Clear History" of sheet 1 of window 1
                        delay 1
                    end tell
                end if
            end tell
            '''
            subprocess.run(['osascript', '-e', script], capture_output=True)
            cleaned_count += 1
        except Exception as e:
            self.errors.append(f"Safari: Unable to clear history via AppleScript: {str(e)}")

        print(f"Removed approximately {cleaned_count} Safari history entries")
        self.entries_removed += cleaned_count
        self.browsers_cleaned.append("Safari")

    def clean_chrome_history(self):
        """Clean Chrome browsing history"""
        print("\n=== Cleaning Chrome History ===")
        cleaned_count = 0

        # Chrome path
        chrome_path = self.home / "Library/Application Support/Google/Chrome"

        if not chrome_path.exists():
            print("Chrome not found on this system.")
            return

        # Find all profile directories
        profile_dirs = []
        try:
            # Look for Default and Profile directories
            if (chrome_path / "Default").exists():
                profile_dirs.append(chrome_path / "Default")

            # Add all numbered Profile directories
            for item in chrome_path.iterdir():
                if item.is_dir() and item.name.startswith("Profile"):
                    profile_dirs.append(item)
        except:
            pass

        if not profile_dirs:
            print("No Chrome profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # History database
            history_db = profile / "History"

            if history_db.exists():
                try:
                    # Create a backup before modification
                    backup_path = history_db.with_suffix(".bak")
                    shutil.copy2(history_db, backup_path)

                    # Create a temporary copy to work with
                    temp_db = history_db.with_name("history_temp.db")
                    if temp_db.exists():
                        os.remove(temp_db)
                    shutil.copy2(history_db, temp_db)

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Count entries
                    cursor.execute("SELECT COUNT(*) FROM urls")
                    count_before = cursor.fetchone()[0]

                    # Delete from urls table
                    cursor.execute("DELETE FROM urls")

                    # Delete from visits table
                    cursor.execute("DELETE FROM visits")

                    # Delete from downloads table
                    cursor.execute("DELETE FROM downloads")

                    # Delete from downloads_url_chains table
                    cursor.execute("DELETE FROM downloads_url_chains")

                    # Vacuum the database
                    cursor.execute("VACUUM")

                    conn.commit()
                    conn.close()

                    # Replace the original database with our cleaned one
                    os.remove(history_db)
                    shutil.move(temp_db, history_db)

                    cleaned_count += count_before
                    print(f"Cleaned Chrome history for {profile.name} ({count_before} entries removed)")
                except Exception as e:
                    self.errors.append(f"Chrome: Error cleaning history from {profile.name}: {str(e)}")
                    print(f"Error: {str(e)}")

                    # Try to restore from backup if available
                    if 'backup_path' in locals() and backup_path.exists():
                        try:
                            shutil.copy2(backup_path, history_db)
                            print(f"Restored {profile.name} history from backup after error")
                        except:
                            pass

        print(f"Removed approximately {cleaned_count} Chrome history entries")
        self.entries_removed += cleaned_count
        self.browsers_cleaned.append("Chrome")

    def clean_firefox_history(self):
        """Clean Firefox browsing history"""
        print("\n=== Cleaning Firefox History ===")
        cleaned_count = 0

        # Find Firefox profile folder
        mozilla_path = self.home / "Library/Application Support/Firefox/Profiles"
        if not mozilla_path.exists():
            print("Firefox not found on this system.")
            return

        profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir() and d.name.endswith('.default')]

        if not profile_dirs:
            # Look for any profile if default not found
            profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir()]

        if not profile_dirs:
            print("No Firefox profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # Places database (contains history)
            places_db = profile / "places.sqlite"

            if places_db.exists():
                try:
                    # Create a backup before modification
                    backup_path = places_db.with_suffix(".bak")
                    shutil.copy2(places_db, backup_path)

                    # Create a temporary copy to work with
                    temp_db = places_db.with_name("places_temp.sqlite")
                    if temp_db.exists():
                        os.remove(temp_db)
                    shutil.copy2(places_db, temp_db)

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Count entries
                    cursor.execute("SELECT COUNT(*) FROM moz_places")
                    count_before = cursor.fetchone()[0]

                    # Delete from places table
                    cursor.execute("DELETE FROM moz_places WHERE id IN (SELECT place_id FROM moz_historyvisits)")

                    # Delete from historyvisits table
                    cursor.execute("DELETE FROM moz_historyvisits")

                    # Delete from inputhistory table
                    cursor.execute("DELETE FROM moz_inputhistory")

                    # Vacuum the database
                    cursor.execute("VACUUM")

                    conn.commit()
                    conn.close()

                    # Replace the original database with our cleaned one
                    os.remove(places_db)
                    shutil.move(temp_db, places_db)

                    cleaned_count += count_before
                    print(f"Cleaned Firefox history for {profile.name} ({count_before} entries removed)")
                except Exception as e:
                    self.errors.append(f"Firefox: Error cleaning history from {profile.name}: {str(e)}")
                    print(f"Error: {str(e)}")

                    # Try to restore from backup if available
                    if 'backup_path' in locals() and backup_path.exists():
                        try:
                            shutil.copy2(backup_path, places_db)
                            print(f"Restored {profile.name} history from backup after error")
                        except:
                            pass

        print(f"Removed approximately {cleaned_count} Firefox history entries")
        self.entries_removed += cleaned_count
        self.browsers_cleaned.append("Firefox")

    def clean_brave_history(self):
        """Clean Brave browsing history"""
        print("\n=== Cleaning Brave History ===")
        cleaned_count = 0

        # Brave path
        brave_path = self.home / "Library/Application Support/BraveSoftware/Brave-Browser"
        if not brave_path.exists():
            brave_path = self.home / "Library/Application Support/Brave-Browser"

        if not brave_path.exists():
            print("Brave not found on this system.")
            return

        # Find all profile directories
        profile_dirs = []
        try:
            # Look for Default and Profile directories
            if (brave_path / "Default").exists():
                profile_dirs.append(brave_path / "Default")

            # Add all numbered Profile directories
            for item in brave_path.iterdir():
                if item.is_dir() and item.name.startswith("Profile"):
                    profile_dirs.append(item)
        except:
            pass

        if not profile_dirs:
            print("No Brave profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # History database
            history_db = profile / "History"

            if history_db.exists():
                try:
                    # Create a backup before modification
                    backup_path = history_db.with_suffix(".bak")
                    shutil.copy2(history_db, backup_path)

                    # Create a temporary copy to work with
                    temp_db = history_db.with_name("history_temp.db")
                    if temp_db.exists():
                        os.remove(temp_db)
                    shutil.copy2(history_db, temp_db)

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Count entries
                    cursor.execute("SELECT COUNT(*) FROM urls")
                    count_before = cursor.fetchone()[0]

                    # Delete from urls table
                    cursor.execute("DELETE FROM urls")

                    # Delete from visits table
                    cursor.execute("DELETE FROM visits")

                    # Delete from downloads table
                    cursor.execute("DELETE FROM downloads")

                    # Delete from downloads_url_chains table
                    cursor.execute("DELETE FROM downloads_url_chains")

                    # Vacuum the database
                    cursor.execute("VACUUM")

                    conn.commit()
                    conn.close()

                    # Replace the original database with our cleaned one
                    os.remove(history_db)
                    shutil.move(temp_db, history_db)

                    cleaned_count += count_before
                    print(f"Cleaned Brave history for {profile.name} ({count_before} entries removed)")
                except Exception as e:
                    self.errors.append(f"Brave: Error cleaning history from {profile.name}: {str(e)}")
                    print(f"Error: {str(e)}")

                    # Try to restore from backup if available
                    if 'backup_path' in locals() and backup_path.exists():
                        try:
                            shutil.copy2(backup_path, history_db)
                            print(f"Restored {profile.name} history from backup after error")
                        except:
                            pass

        print(f"Removed approximately {cleaned_count} Brave history entries")
        self.entries_removed += cleaned_count
        self.browsers_cleaned.append("Brave")

    def clean_all_history(self):
        """Clean history from all browsers"""
        print("Browser History Cleaner starting...")

        # Display warning about potential login issues
        print("\n⚠️ WARNING ⚠️")
        print("Cleaning browser history may cause you to be logged out of some websites.")
        print("This happens because some sites link their login sessions to browsing history.")
        print("Continue only if you're willing to potentially re-login to websites.")

        if self.confirm_deletion:
            response = input("\nDo you want to continue? (y/n): ").strip().lower()
            if response != 'y':
                print("History cleaning cancelled.")
                return

        # Clean each browser's history
        self.clean_safari_history()
        self.clean_chrome_history()
        self.clean_firefox_history()
        self.clean_brave_history()

        print("\nCleaning complete!")
        print(f"Browsers cleaned: {', '.join(self.browsers_cleaned) if self.browsers_cleaned else 'None'}")
        print(f"Approximate entries removed: {self.entries_removed}")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"- {error}")

        print("\nNOTE: You may need to restart your browsers for the changes to take full effect.")
        print("Also be prepared to re-login to some websites where you were previously logged in.")

if __name__ == "__main__":
    cleaner = BrowserHistoryCleaner()

    # Parse command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == '--no-confirm':
        cleaner.confirm_deletion = False

    cleaner.clean_all_history()