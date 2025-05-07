import os
import sqlite3
import json
import time
import datetime
from pathlib import Path
import sys

class BrowserCacheViewer:
    def __init__(self):
        self.home = Path.home()
        self.browsers_analyzed = []
        self.errors = []
        self.sample_size = 20  # Limit to 20 entries by default

    def format_timestamp(self, timestamp, browser_type='chrome'):
        """Format timestamp based on browser type"""
        try:
            if browser_type == 'chrome' or browser_type == 'brave':
                # Chrome/Brave timestamp is microseconds since Jan 1, 1601
                if timestamp > 13000000000000000:  # It's in microseconds
                    timestamp = timestamp / 1000000  # Convert to seconds
                elif timestamp > 13000000000000:  # It's in milliseconds
                    timestamp = timestamp / 1000  # Convert to seconds

                # Adjust for Chrome's epoch (Jan 1, 1601)
                chrome_epoch_offset = 11644473600  # Seconds between 1601 and 1970
                unix_timestamp = timestamp - chrome_epoch_offset

                if unix_timestamp < 0:
                    return "Invalid timestamp"

                return datetime.datetime.fromtimestamp(unix_timestamp).strftime('%Y-%m-%d %H:%M:%S')

            elif browser_type == 'firefox':
                # Firefox timestamp is microseconds since Jan 1, 1970
                unix_timestamp = timestamp / 1000000
                return datetime.datetime.fromtimestamp(unix_timestamp).strftime('%Y-%m-%d %H:%M:%S')

            elif browser_type == 'safari':
                # Safari timestamp is seconds since Jan 1, 1970
                return datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

            else:
                return str(timestamp)
        except:
            return str(timestamp)

    def view_safari_cache(self):
        """View Safari cache details"""
        print("\n=== Safari Cache Details ===")
        cache_entries = []

        # Safari cache database paths
        cache_paths = [
            self.home / "Library/Safari/History.db",
            self.home / "Library/Caches/com.apple.Safari/Cache.db"
        ]

        for path in cache_paths:
            if not path.exists():
                continue

            try:
                # Connect to the database
                conn = sqlite3.connect(str(path))
                cursor = conn.cursor()

                if path.name == "History.db":
                    # Try to extract from history DB
                    try:
                        cursor.execute("""
                            SELECT h.url, v.visit_time
                            FROM history_items h
                            JOIN history_visits v ON h.id = v.history_item
                            ORDER BY v.visit_time DESC
                            LIMIT ?
                        """, (self.sample_size,))

                        for row in cursor.fetchall():
                            url = row[0]
                            timestamp = row[1]

                            cache_entries.append({
                                'url': url,
                                'timestamp': self.format_timestamp(timestamp, 'safari'),
                                'source': 'History DB'
                            })
                    except:
                        pass

                elif path.name == "Cache.db":
                    # Try to extract from cache DB
                    try:
                        # First check what tables are available
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                        tables = [row[0] for row in cursor.fetchall()]

                        if 'cfurl_cache_response' in tables:
                            cursor.execute("""
                                SELECT request_key, time_stamp FROM cfurl_cache_response
                                ORDER BY time_stamp DESC
                                LIMIT ?
                            """, (self.sample_size,))

                            for row in cursor.fetchall():
                                url = row[0]
                                timestamp = row[1]

                                cache_entries.append({
                                    'url': url,
                                    'timestamp': self.format_timestamp(timestamp, 'safari'),
                                    'source': 'Cache DB'
                                })
                    except:
                        pass

                conn.close()
            except Exception as e:
                self.errors.append(f"Safari: Error reading {path.name}: {str(e)}")

        # Display results
        if cache_entries:
            cache_entries = cache_entries[:self.sample_size]  # Limit to sample size
            print(f"Found {len(cache_entries)} cache entries:")
            for i, entry in enumerate(cache_entries):
                print(f"{i+1}. URL: {entry['url']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Source: {entry['source']}")
                print("")

            self.browsers_analyzed.append("Safari")
        else:
            print("No Safari cache entries found.")

        return cache_entries

    def view_chrome_cache(self):
        """View Chrome cache details"""
        print("\n=== Chrome Cache Details ===")
        cache_entries = []

        # Chrome path
        chrome_path = self.home / "Library/Application Support/Google/Chrome"

        if not chrome_path.exists():
            print("Chrome not found on this system.")
            return cache_entries

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
            return cache_entries

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # History database
            history_db = profile / "History"

            if history_db.exists():
                try:
                    # Create a temporary copy to avoid database lock
                    temp_db = history_db.parent / "history_temp.db"
                    if temp_db.exists():
                        os.remove(temp_db)

                    # Copy file
                    with open(history_db, 'rb') as src, open(temp_db, 'wb') as dst:
                        dst.write(src.read())

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Extract URL and visit timestamps
                    try:
                        cursor.execute("""
                            SELECT u.url, v.visit_time
                            FROM urls u
                            JOIN visits v ON u.id = v.url
                            ORDER BY v.visit_time DESC
                            LIMIT ?
                        """, (self.sample_size,))

                        for row in cursor.fetchall():
                            url = row[0]
                            timestamp = row[1]

                            cache_entries.append({
                                'url': url,
                                'timestamp': self.format_timestamp(timestamp, 'chrome'),
                                'source': f'Chrome {profile.name}'
                            })
                    except Exception as e:
                        self.errors.append(f"Chrome: Error reading history from {profile.name}: {str(e)}")

                    conn.close()

                    # Remove temporary file
                    if temp_db.exists():
                        os.remove(temp_db)
                except Exception as e:
                    self.errors.append(f"Chrome: Error accessing history database from {profile.name}: {str(e)}")

        # Display results
        if cache_entries:
            cache_entries = cache_entries[:self.sample_size]  # Limit to sample size
            print(f"Found {len(cache_entries)} cache entries:")
            for i, entry in enumerate(cache_entries):
                print(f"{i+1}. URL: {entry['url']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Source: {entry['source']}")
                print("")

            self.browsers_analyzed.append("Chrome")
        else:
            print("No Chrome cache entries found.")

        return cache_entries

    def view_firefox_cache(self):
        """View Firefox cache details"""
        print("\n=== Firefox Cache Details ===")
        cache_entries = []

        # Find Firefox profile folder
        mozilla_path = self.home / "Library/Application Support/Firefox/Profiles"
        if not mozilla_path.exists():
            print("Firefox not found on this system.")
            return cache_entries

        profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir() and d.name.endswith('.default')]

        if not profile_dirs:
            # Look for any profile if default not found
            profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir()]

        if not profile_dirs:
            print("No Firefox profiles found.")
            return cache_entries

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # Places database (contains history and cache data)
            places_db = profile / "places.sqlite"

            if places_db.exists():
                try:
                    # Create a temporary copy to avoid database lock
                    temp_db = places_db.parent / "places_temp.sqlite"
                    if temp_db.exists():
                        os.remove(temp_db)

                    # Copy file
                    with open(places_db, 'rb') as src, open(temp_db, 'wb') as dst:
                        dst.write(src.read())

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Extract URL and visit timestamps
                    try:
                        cursor.execute("""
                            SELECT p.url, h.visit_date
                            FROM moz_places p
                            JOIN moz_historyvisits h ON p.id = h.place_id
                            ORDER BY h.visit_date DESC
                            LIMIT ?
                        """, (self.sample_size,))

                        for row in cursor.fetchall():
                            url = row[0]
                            timestamp = row[1]

                            cache_entries.append({
                                'url': url,
                                'timestamp': self.format_timestamp(timestamp, 'firefox'),
                                'source': f'Firefox {profile.name}'
                            })
                    except Exception as e:
                        self.errors.append(f"Firefox: Error reading places from {profile.name}: {str(e)}")

                    conn.close()

                    # Remove temporary file
                    if temp_db.exists():
                        os.remove(temp_db)
                except Exception as e:
                    self.errors.append(f"Firefox: Error accessing places database from {profile.name}: {str(e)}")

        # Display results
        if cache_entries:
            cache_entries = cache_entries[:self.sample_size]  # Limit to sample size
            print(f"Found {len(cache_entries)} cache entries:")
            for i, entry in enumerate(cache_entries):
                print(f"{i+1}. URL: {entry['url']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Source: {entry['source']}")
                print("")

            self.browsers_analyzed.append("Firefox")
        else:
            print("No Firefox cache entries found.")

        return cache_entries

    def view_brave_cache(self):
        """View Brave cache details"""
        print("\n=== Brave Cache Details ===")
        cache_entries = []

        # Brave path
        brave_path = self.home / "Library/Application Support/BraveSoftware/Brave-Browser"
        if not brave_path.exists():
            brave_path = self.home / "Library/Application Support/Brave-Browser"

        if not brave_path.exists():
            print("Brave not found on this system.")
            return cache_entries

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
            return cache_entries

        for profile in profile_dirs:
            print(f"\nProfile: {profile.name}")

            # History database
            history_db = profile / "History"

            if history_db.exists():
                try:
                    # Create a temporary copy to avoid database lock
                    temp_db = history_db.parent / "history_temp.db"
                    if temp_db.exists():
                        os.remove(temp_db)

                    # Copy file
                    with open(history_db, 'rb') as src, open(temp_db, 'wb') as dst:
                        dst.write(src.read())

                    # Connect to the database
                    conn = sqlite3.connect(str(temp_db))
                    cursor = conn.cursor()

                    # Extract URL and visit timestamps
                    try:
                        cursor.execute("""
                            SELECT u.url, v.visit_time
                            FROM urls u
                            JOIN visits v ON u.id = v.url
                            ORDER BY v.visit_time DESC
                            LIMIT ?
                        """, (self.sample_size,))

                        for row in cursor.fetchall():
                            url = row[0]
                            timestamp = row[1]

                            cache_entries.append({
                                'url': url,
                                'timestamp': self.format_timestamp(timestamp, 'brave'),
                                'source': f'Brave {profile.name}'
                            })
                    except Exception as e:
                        self.errors.append(f"Brave: Error reading history from {profile.name}: {str(e)}")

                    conn.close()

                    # Remove temporary file
                    if temp_db.exists():
                        os.remove(temp_db)
                except Exception as e:
                    self.errors.append(f"Brave: Error accessing history database from {profile.name}: {str(e)}")

        # Display results
        if cache_entries:
            cache_entries = cache_entries[:self.sample_size]  # Limit to sample size
            print(f"Found {len(cache_entries)} cache entries:")
            for i, entry in enumerate(cache_entries):
                print(f"{i+1}. URL: {entry['url']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Source: {entry['source']}")
                print("")

            self.browsers_analyzed.append("Brave")
        else:
            print("No Brave cache entries found.")

        return cache_entries

    def run_analysis(self):
        """Run analysis on all browsers"""
        print("Browser Cache Viewer starting...")
        print(f"Sample size: {self.sample_size} entries per browser")

        all_entries = []

        # Analyze each browser
        safari_entries = self.view_safari_cache()
        chrome_entries = self.view_chrome_cache()
        firefox_entries = self.view_firefox_cache()
        brave_entries = self.view_brave_cache()

        # Combine entries
        all_entries.extend(safari_entries)
        all_entries.extend(chrome_entries)
        all_entries.extend(firefox_entries)
        all_entries.extend(brave_entries)

        # Sort by timestamp (newest first)
        all_entries.sort(key=lambda x: x['timestamp'], reverse=True)

        # Display combined results
        if all_entries:
            print("\n=== Combined Recent Browser Activity ===")
            print(f"Top {min(self.sample_size, len(all_entries))} most recent entries across all browsers:")

            for i, entry in enumerate(all_entries[:self.sample_size]):
                print(f"{i+1}. URL: {entry['url']}")
                print(f"   Timestamp: {entry['timestamp']}")
                print(f"   Source: {entry['source']}")
                print("")

        print("\nAnalysis complete!")
        print(f"Browsers analyzed: {', '.join(self.browsers_analyzed) if self.browsers_analyzed else 'None'}")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"- {error}")

        return all_entries

    def set_sample_size(self, size):
        """Set the sample size"""
        try:
            size = int(size)
            if size > 0:
                self.sample_size = size
                print(f"Sample size set to {size} entries")
            else:
                print("Sample size must be a positive integer")
        except:
            print("Invalid sample size")

if __name__ == "__main__":
    viewer = BrowserCacheViewer()

    # Parse command line arguments
    if len(sys.argv) > 1:
        try:
            sample_size = int(sys.argv[1])
            viewer.set_sample_size(sample_size)
        except:
            print("Invalid sample size argument. Using default sample size.")

    viewer.run_analysis()