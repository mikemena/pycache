import os
import sqlite3
import time
from pathlib import Path
import sys
import shutil
import subprocess
import argparse
import datetime

class BrowserDataCleaner:
    def __init__(self):
        self.home = Path.home()
        self.browsers_cleaned = []
        self.errors = []
        self.history_entries_removed = 0
        self.cache_size_cleaned = 0
        self.confirm_deletion = True  # Require confirmation before deleting

        # Default cleaning options
        self.clean_history = False
        self.clean_cache = False
        self.clean_cookies = False

        # Time range (in hours, 0 means all time)
        self.time_range = 1  # Default to last hour

    def format_bytes(self, size):
        """Format bytes to a human-readable format"""
        power = 2**10  # 1024
        n = 0
        power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
        while size > power:
            size /= power
            n += 1
        return f"{size:.2f} {power_labels[n]}"

    def get_cutoff_time(self):
        """Get cutoff timestamp based on time_range"""
        if self.time_range == 0:
            return {
                'chrome': 0,
                'brave': 0,
                'firefox': 0,
                'unix': 0
            }  # All time

        # Calculate cutoff time in seconds since epoch
        current_time = time.time()
        cutoff_time = current_time - (self.time_range * 3600)

        # For Chrome/Brave, convert to their format (microseconds since 1601)
        chrome_epoch_offset = 11644473600  # Seconds between 1601 and 1970
        chrome_cutoff = (cutoff_time + chrome_epoch_offset) * 1000000

        # For Firefox, convert to microseconds since 1970
        firefox_cutoff = cutoff_time * 1000000

        return {
            'chrome': chrome_cutoff,
            'brave': chrome_cutoff,
            'firefox': firefox_cutoff,
            'unix': cutoff_time
        }

    def clean_chrome_data(self):
        """Clean Chrome data based on selected options"""
        print("\n=== Cleaning Chrome Data ===")
        history_count = 0
        cache_size = 0

        # Get cutoff time
        cutoff_times = self.get_cutoff_time()
        chrome_cutoff = cutoff_times['chrome']

        # Chrome path
        chrome_path = self.home / "Library/Application Support/Google/Chrome"
        if os.name == 'nt':  # Windows
            chrome_path = self.home / "AppData/Local/Google/Chrome/User Data"
        elif os.name == 'posix' and not sys.platform.startswith('darwin'):  # Linux
            chrome_path = self.home / ".config/google-chrome"

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
        except Exception as e:
            self.errors.append(f"Chrome: Error finding profiles: {str(e)}")

        if not profile_dirs:
            print("No Chrome profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # Clean history if selected
            if self.clean_history:
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

                        # First check the schema to determine correct column names
                        cursor.execute("PRAGMA table_info(visits)")
                        visits_columns = [col[1] for col in cursor.fetchall()]

                        # Determine which column is the URL ID (could be url_id or url)
                        url_id_column = "url_id" if "url_id" in visits_columns else "url"

                        # Count entries before deletion
                        if self.time_range == 0:  # All time
                            cursor.execute("SELECT COUNT(*) FROM urls")
                        else:
                            cursor.execute(f"SELECT COUNT(*) FROM visits WHERE visit_time > ?", (chrome_cutoff,))
                        count_before = cursor.fetchone()[0]

                        if self.time_range == 0:  # All time
                            # Delete all history
                            cursor.execute("DELETE FROM urls")
                            cursor.execute("DELETE FROM visits")
                            try:
                                cursor.execute("DELETE FROM keyword_search_terms")
                            except:
                                pass  # Table may not exist
                        else:
                            # Delete based on time range
                            # First get the URLs to delete
                            cursor.execute(f"""
                                SELECT {url_id_column} FROM visits
                                WHERE visit_time > ?
                            """, (chrome_cutoff,))

                            url_ids = [row[0] for row in cursor.fetchall()]

                            if url_ids:
                                # Delete visits
                                cursor.execute("DELETE FROM visits WHERE visit_time > ?", (chrome_cutoff,))

                                # Cleanup search terms if table exists
                                try:
                                    if cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='keyword_search_terms'").fetchone():
                                        # Build URL list for IN clause
                                        placeholders = ','.join(['?'] * len(url_ids))

                                        # Delete search terms for these URLs
                                        cursor.execute(f"""
                                            DELETE FROM keyword_search_terms
                                            WHERE url_id IN ({placeholders})
                                        """, url_ids)
                                except:
                                    pass  # Table may not exist

                                # Delete orphaned URLs
                                cursor.execute(f"""
                                    DELETE FROM urls
                                    WHERE id NOT IN (SELECT DISTINCT {url_id_column} FROM visits)
                                """)

                        # Commit transaction
                        conn.commit()

                        # Vacuum the database (must be outside transaction)
                        conn.execute("VACUUM")
                        conn.close()

                        # Replace the original database with our cleaned one
                        os.remove(history_db)
                        shutil.move(temp_db, history_db)

                        # Remove backup if cleanup was successful
                        if backup_path.exists():
                            os.remove(backup_path)

                        history_count += count_before
                        print(f"Removed {count_before} Chrome history entries")
                    except Exception as e:
                        # Try to restore from backup if it exists
                        if backup_path.exists() and not history_db.exists():
                            shutil.copy2(backup_path, history_db)

                        self.errors.append(f"Chrome: Error cleaning history from {profile.name}: {str(e)}")

            # Clean cache if selected
            if self.clean_cache:
                cache_dir = profile / "Cache"
                if os.name == 'nt':  # Windows has a different cache structure
                    cache_dirs = [
                        profile / "Cache",
                        profile / "Code Cache",
                        profile / "GPUCache"
                    ]
                else:
                    cache_dirs = [
                        profile / "Cache",
                        profile / "Code Cache",
                        profile / "GPUCache"
                    ]

                for cache_path in cache_dirs:
                    if not cache_path.exists():
                        continue

                    try:
                        # Calculate size before deletion
                        size = sum(f.stat().st_size for f in cache_path.glob('**/*') if f.is_file())
                        cache_size += size

                        # Delete all files in cache directory
                        for item in cache_path.glob('**/*'):
                            if item.is_file():
                                try:
                                    item.unlink(missing_ok=True)
                                except:
                                    pass  # Skip files that can't be deleted

                        print(f"Cleared {self.format_bytes(size)} from {cache_path.name}")
                    except Exception as e:
                        self.errors.append(f"Chrome: Error cleaning cache at {cache_path}: {str(e)}")

        # Update totals
        self.history_entries_removed += history_count
        self.cache_size_cleaned += cache_size

        if history_count > 0 or cache_size > 0:
            self.browsers_cleaned.append("Chrome")

    def clean_firefox_data(self):
        """Clean Firefox data based on selected options"""
        print("\n=== Cleaning Firefox Data ===")
        history_count = 0
        cache_size = 0

        # Get cutoff time
        cutoff_times = self.get_cutoff_time()
        firefox_cutoff = cutoff_times['firefox']

        # Firefox profile path
        firefox_path = None
        if sys.platform.startswith('darwin'):  # macOS
            firefox_path = self.home / "Library/Application Support/Firefox/Profiles"
        elif os.name == 'nt':  # Windows
            firefox_path = self.home / "AppData/Roaming/Mozilla/Firefox/Profiles"
        else:  # Linux
            firefox_path = self.home / ".mozilla/firefox"

        if not firefox_path or not firefox_path.exists():
            print("Firefox profiles directory not found on this system.")
            return

        # Find all profile directories
        profile_dirs = []
        try:
            for item in firefox_path.iterdir():
                if item.is_dir() and (item.name.endswith(".default") or ".default-" in item.name or item.name.endswith("release")):
                    profile_dirs.append(item)
        except Exception as e:
            self.errors.append(f"Firefox: Error finding profiles: {str(e)}")

        if not profile_dirs:
            print("No Firefox profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # Clean history if selected
            if self.clean_history:
                # Places database (contains history, bookmarks, etc.)
                places_db = profile / "places.sqlite"

                if places_db.exists():
                    try:
                        # Create a backup before modification
                        backup_path = places_db.with_suffix(".bak")
                        shutil.copy2(places_db, backup_path)

                        # Create a temporary copy to work with (to avoid locking issues)
                        temp_db = places_db.with_name("places_temp.sqlite")
                        if temp_db.exists():
                            os.remove(temp_db)
                        shutil.copy2(places_db, temp_db)

                        # Connect to the database
                        conn = sqlite3.connect(str(temp_db))
                        cursor = conn.cursor()

                        # Count entries before deletion
                        if self.time_range == 0:  # All time
                            cursor.execute("SELECT COUNT(*) FROM moz_places")
                            count_before = cursor.fetchone()[0]
                        else:
                            cursor.execute("SELECT COUNT(*) FROM moz_historyvisits WHERE visit_date > ?", (firefox_cutoff,))
                            count_before = cursor.fetchone()[0]

                        if self.time_range == 0:  # All time
                            # Delete all history, but preserve bookmarks
                            cursor.execute("DELETE FROM moz_historyvisits")
                            cursor.execute("""
                                DELETE FROM moz_places
                                WHERE id NOT IN (
                                    SELECT place_id FROM moz_bookmarks
                                )
                            """)
                        else:
                            # Get IDs of history visits to remove
                            cursor.execute("""
                                SELECT place_id FROM moz_historyvisits
                                WHERE visit_date > ?
                            """, (firefox_cutoff,))

                            # Delete visits based on time
                            cursor.execute("DELETE FROM moz_historyvisits WHERE visit_date > ?", (firefox_cutoff,))

                            # Clean up orphaned places (that are not bookmarks)
                            cursor.execute("""
                                DELETE FROM moz_places
                                WHERE id NOT IN (
                                    SELECT place_id FROM moz_historyvisits
                                    UNION
                                    SELECT place_id FROM moz_bookmarks
                                )
                            """)

                        # Commit transaction
                        conn.commit()

                        # Vacuum the database (must be outside transaction)
                        conn.execute("VACUUM")
                        conn.close()

                        # Replace the original database with our cleaned one
                        os.remove(places_db)
                        shutil.move(temp_db, places_db)

                        # Remove backup if cleanup was successful
                        if backup_path.exists():
                            os.remove(backup_path)

                        history_count += count_before
                        print(f"Removed {count_before} Firefox history entries")
                    except Exception as e:
                        # Try to restore from backup if it exists
                        if backup_path.exists() and not places_db.exists():
                            shutil.copy2(backup_path, places_db)

                        self.errors.append(f"Firefox: Error cleaning history from {profile.name}: {str(e)}")

            # Clean cache if selected
            if self.clean_cache:
                cache_dir = profile / "cache2"

                if cache_dir.exists():
                    try:
                        # Calculate size before deletion
                        size = sum(f.stat().st_size for f in cache_dir.glob('**/*') if f.is_file())
                        cache_size += size

                        # Delete all files in cache directory
                        for item in cache_dir.glob('**/*'):
                            if item.is_file():
                                try:
                                    item.unlink(missing_ok=True)
                                except:
                                    pass  # Skip files that can't be deleted

                        print(f"Cleared {self.format_bytes(size)} from Firefox cache")
                    except Exception as e:
                        self.errors.append(f"Firefox: Error cleaning cache at {cache_dir}: {str(e)}")

        # Update totals
        self.history_entries_removed += history_count
        self.cache_size_cleaned += cache_size

        if history_count > 0 or cache_size > 0:
            self.browsers_cleaned.append("Firefox")

    def clean_brave_data(self):
        """Clean Brave data based on selected options"""
        print("\n=== Cleaning Brave Data ===")
        history_count = 0
        cache_size = 0

        # Get cutoff time
        cutoff_times = self.get_cutoff_time()
        brave_cutoff = cutoff_times['brave']

        # Brave path
        brave_path = None
        if sys.platform.startswith('darwin'):  # macOS
            brave_path = self.home / "Library/Application Support/BraveSoftware/Brave-Browser"
        elif os.name == 'nt':  # Windows
            brave_path = self.home / "AppData/Local/BraveSoftware/Brave-Browser/User Data"
        else:  # Linux
            brave_path = self.home / ".config/BraveSoftware/Brave-Browser"

        if not brave_path or not brave_path.exists():
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
        except Exception as e:
            self.errors.append(f"Brave: Error finding profiles: {str(e)}")

        if not profile_dirs:
            print("No Brave profiles found.")
            return

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # Clean history if selected
            if self.clean_history:
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

                        # First check the schema to determine correct column names
                        cursor.execute("PRAGMA table_info(visits)")
                        visits_columns = [col[1] for col in cursor.fetchall()]

                        # Determine which column is the URL ID (could be url_id or url)
                        url_id_column = "url_id" if "url_id" in visits_columns else "url"

                        # Count entries before deletion
                        if self.time_range == 0:  # All time
                            cursor.execute("SELECT COUNT(*) FROM urls")
                        else:
                            cursor.execute(f"SELECT COUNT(*) FROM visits WHERE visit_time > ?", (brave_cutoff,))
                        count_before = cursor.fetchone()[0]

                        # Begin transaction - FIX for VACUUM error
                        conn.execute("BEGIN IMMEDIATE TRANSACTION")

                        if self.time_range == 0:  # All time
                            # Delete all history
                            cursor.execute("DELETE FROM urls")
                            cursor.execute("DELETE FROM visits")
                            try:
                                cursor.execute("DELETE FROM keyword_search_terms")
                            except:
                                pass  # Table may not exist
                        else:
                            # Delete based on time range
                            # First get the URLs to delete
                            cursor.execute(f"""
                                SELECT {url_id_column} FROM visits
                                WHERE visit_time > ?
                            """, (brave_cutoff,))

                            url_ids = [row[0] for row in cursor.fetchall()]

                            if url_ids:
                                # Delete visits
                                cursor.execute("DELETE FROM visits WHERE visit_time > ?", (brave_cutoff,))

                                # Cleanup search terms if table exists
                                try:
                                    if cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='keyword_search_terms'").fetchone():
                                        # Build URL list for IN clause
                                        placeholders = ','.join(['?'] * len(url_ids))

                                        # Delete search terms for these URLs
                                        cursor.execute(f"""
                                            DELETE FROM keyword_search_terms
                                            WHERE url_id IN ({placeholders})
                                        """, url_ids)
                                except:
                                    pass  # Table may not exist

                                # Delete orphaned URLs
                                cursor.execute(f"""
                                    DELETE FROM urls
                                    WHERE id NOT IN (SELECT DISTINCT {url_id_column} FROM visits)
                                """)

                        # Commit transaction before VACUUM - FIX for VACUUM error
                        conn.commit()

                        # Vacuum the database - needs to be outside transaction
                        conn.execute("VACUUM")

                        conn.close()

                        # Replace the original database with our cleaned one
                        os.remove(history_db)
                        shutil.move(temp_db, history_db)

                        # Remove backup if cleanup was successful
                        if backup_path.exists():
                            os.remove(backup_path)

                        history_count += count_before
                        print(f"Removed {count_before} Brave history entries")
                    except Exception as e:
                        # Try to restore from backup if it exists
                        if backup_path.exists() and not history_db.exists():
                            shutil.copy2(backup_path, history_db)

                        self.errors.append(f"Brave: Error cleaning history from {profile.name}: {str(e)}")

            # Clean cache if selected
            if self.clean_cache:
                cache_dirs = [
                    profile / "Cache",
                    profile / "Code Cache",
                    profile / "GPUCache"
                ]

                for cache_path in cache_dirs:
                    if not cache_path.exists():
                        continue

                    try:
                        # Calculate size before deletion
                        size = sum(f.stat().st_size for f in cache_path.glob('**/*') if f.is_file())
                        cache_size += size

                        # Delete all files in cache directory
                        for item in cache_path.glob('**/*'):
                            if item.is_file():
                                try:
                                    item.unlink(missing_ok=True)
                                except:
                                    pass  # Skip files that can't be deleted

                        print(f"Cleared {self.format_bytes(size)} from {cache_path.name}")
                    except Exception as e:
                        self.errors.append(f"Brave: Error cleaning cache at {cache_path}: {str(e)}")

        # Update totals
        self.history_entries_removed += history_count
        self.cache_size_cleaned += cache_size

        if history_count > 0 or cache_size > 0:
            self.browsers_cleaned.append("Brave")

    def clean_browser_data(self):
        """Clean data from all selected browsers"""
        # Chrome
        try:
            self.clean_chrome_data()
        except Exception as e:
            self.errors.append(f"Chrome: General error: {str(e)}")

        # Firefox
        try:
            self.clean_firefox_data()
        except Exception as e:
            self.errors.append(f"Firefox: General error: {str(e)}")

        # Brave
        try:
            self.clean_brave_data()
        except Exception as e:
            self.errors.append(f"Brave: General error: {str(e)}")

        # Print summary
        print("\n=== Cleaning Summary ===")
        if self.browsers_cleaned:
            print(f"Browsers cleaned: {', '.join(self.browsers_cleaned)}")
            print(f"History entries removed: {self.history_entries_removed}")
            print(f"Cache size freed: {self.format_bytes(self.cache_size_cleaned)}")
        else:
            print("No browser data was cleaned.")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"- {error}")

            print("\nNote: Some errors are expected due to macOS security restrictions.")
            print("The cleaning was still performed where possible.")
        else:
            print("\nNo errors encountered during cleaning.")

def main():
    parser = argparse.ArgumentParser(description="Clean browser history and cache data")

    # General options
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompts")

    # Browser selection
    browsers_group = parser.add_argument_group("Browser Selection")
    browsers_group.add_argument("--chrome", action="store_true", help="Clean Chrome data")
    browsers_group.add_argument("--firefox", action="store_true", help="Clean Firefox data")
    browsers_group.add_argument("--brave", action="store_true", help="Clean Brave data")
    browsers_group.add_argument("--all", action="store_true", help="Clean data from all supported browsers")

    # Data types to clean
    data_group = parser.add_argument_group("Data Types")
    data_group.add_argument("--history", action="store_true", help="Clean browsing history")
    data_group.add_argument("--cache", action="store_true", help="Clean browser cache")
    data_group.add_argument("--cookies", action="store_true", help="Clean cookies (not fully implemented yet)")

    # Time range
    time_group = parser.add_argument_group("Time Range")
    time_range = time_group.add_mutually_exclusive_group()
    time_range.add_argument("--hour", action="store_const", const=1, dest="time_range",
                          help="Clean data from the last hour")
    time_range.add_argument("--day", action="store_const", const=24, dest="time_range",
                          help="Clean data from today (last 24 hours)")
    time_range.add_argument("--week", action="store_const", const=168, dest="time_range",
                          help="Clean data from the last week")
    time_range.add_argument("--all-time", action="store_const", const=0, dest="time_range",
                          help="Clean all data regardless of time")
    parser.set_defaults(time_range=1)  # Default to last hour

    args = parser.parse_args()

    # Initialize the cleaner
    cleaner = BrowserDataCleaner()

    # Set options based on arguments
    cleaner.clean_history = args.history
    cleaner.clean_cache = args.cache
    cleaner.clean_cookies = args.cookies
    cleaner.time_range = args.time_range
    cleaner.confirm_deletion = not args.yes

    # If no data types specified, prompt user
    if not (args.history or args.cache or args.cookies):
        print("No data types specified for cleaning.")
        response = input("Would you like to clean browsing history? (y/n): ").lower()
        cleaner.clean_history = response.startswith('y')

        response = input("Would you like to clean browser cache? (y/n): ").lower()
        cleaner.clean_cache = response.startswith('y')

    # If no browsers specified, prompt user
    browsers_selected = args.chrome or args.firefox or args.brave or args.all
    if not browsers_selected:
        print("No browsers specified for cleaning.")
        response = input("Would you like to clean all supported browsers? (y/n): ").lower()
        if response.startswith('y'):
            args.all = True
        else:
            response = input("Clean Chrome? (y/n): ").lower()
            args.chrome = response.startswith('y')

            response = input("Clean Firefox? (y/n): ").lower()
            args.firefox = response.startswith('y')

            response = input("Clean Brave? (y/n): ").lower()
            args.brave = response.startswith('y')

    # Get time range description for confirmation message
    time_desc = "the last hour"
    if args.time_range == 0:
        time_desc = "all time"
    elif args.time_range == 24:
        time_desc = "today (last 24 hours)"
    elif args.time_range == 168:
        time_desc = "the last week"

    # Confirm with user
    if cleaner.confirm_deletion:
        data_types = []
        if cleaner.clean_history:
            data_types.append("browsing history")
        if cleaner.clean_cache:
            data_types.append("cache")
        if cleaner.clean_cookies:
            data_types.append("cookies")

        browsers = []
        if args.all:
            browsers.append("all supported browsers")
        else:
            if args.chrome:
                browsers.append("Chrome")
            if args.firefox:
                browsers.append("Firefox")
            if args.brave:
                browsers.append("Brave")

        if not browsers:
            print("No browsers selected for cleaning. Exiting.")
            return

        print(f"\nYou are about to clean {', '.join(data_types)} from {', '.join(browsers)} for {time_desc}.")
        confirm = input("Do you want to continue? (y/n): ").lower()

        if not confirm.startswith('y'):
            print("Operation cancelled.")
            return

    # Clean selected browsers
    if args.all or args.chrome:
        try:
            cleaner.clean_chrome_data()
        except Exception as e:
            cleaner.errors.append(f"Chrome: Unexpected error: {str(e)}")

    if args.all or args.firefox:
        try:
            cleaner.clean_firefox_data()
        except Exception as e:
            cleaner.errors.append(f"Firefox: Unexpected error: {str(e)}")

    if args.all or args.brave:
        try:
            cleaner.clean_brave_data()
        except Exception as e:
            cleaner.errors.append(f"Brave: Unexpected error: {str(e)}")

    # Print summary
    print("\n=== Cleaning Complete! ===")
    if cleaner.browsers_cleaned:
        print(f"Browsers cleaned: {', '.join(cleaner.browsers_cleaned)}")
        print(f"History entries removed: {cleaner.history_entries_removed}")
        print(f"Cache size freed: {cleaner.format_bytes(cleaner.cache_size_cleaned)}")
    else:
        print("No browser data was cleaned.")

    if cleaner.errors:
        print("\nErrors encountered:")
        for error in cleaner.errors:
            print(f"- {error}")

        print("\nNote: Some errors are expected due to macOS security restrictions.")
        print("The cleaning was still performed where possible.")

if __name__ == "__main__":
    main()