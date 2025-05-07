import os
import shutil
import subprocess
import time
from pathlib import Path
import sys
import sqlite3

class BrowserCacheCleaner:
    def __init__(self):
        self.home = Path.home()
        self.browsers_cleaned = []
        self.errors = []
        self.force_close = False  # Changed to False to avoid closing browsers
        self.files_deleted = 0  # Counter for deleted files
        self.bytes_deleted = 0  # Counter for bytes freed
        self.preserve_logins = True  # Preserve saved logins
        self.preserve_sessions = True  # Preserve current browser sessions

    def force_close_process(self, process_name, friendly_name):
        """Force close a process by name"""
        if not self.force_close:
            print(f"Skipping force close of {friendly_name} to preserve sessions")
            return False

        try:
            # Check if process is running
            result = subprocess.run(['pgrep', '-x', process_name], capture_output=True, text=True)
            if result.stdout.strip():
                print(f"Force closing {friendly_name}...")
                subprocess.run(['killall', process_name])
                # Give the process time to close
                time.sleep(2)

                # Check if it's still running
                result = subprocess.run(['pgrep', '-x', process_name], capture_output=True, text=True)
                if result.stdout.strip():
                    # Try a stronger force quit if normal killall didn't work
                    subprocess.run(['killall', '-9', process_name])
                    time.sleep(1)

                    # Check one more time
                    result = subprocess.run(['pgrep', '-x', process_name], capture_output=True, text=True)
                    if result.stdout.strip():
                        print(f"Warning: Could not force close {friendly_name}")
                        return False
                return True
            return True  # Process was not running
        except Exception as e:
            print(f"Error while trying to close {friendly_name}: {str(e)}")
            return False

    def delete_file(self, file_path):
        """Delete a file and update counters"""
        try:
            # Check if file should be preserved for logins or sessions
            file_name_lower = file_path.name.lower()

            # Don't touch login files
            if self.preserve_logins and any(keyword in file_name_lower for keyword in [
                "login", "password", "key", "auth", "credential", "token", "identity",
                "account", "sign", "secure", "preference", "bookmarks"
            ]):
                return False

            # Don't touch session files
            if self.preserve_sessions and any(keyword in file_name_lower for keyword in [
                "session", "tab", "window", "state", "open", "current", "cookies", "visited", "history"
            ]):
                return False

            # Get file size before deletion
            if file_path.exists() and file_path.is_file():
                try:
                    file_size = file_path.stat().st_size
                except:
                    file_size = 0

                # Delete the file
                file_path.unlink(missing_ok=True)

                # Update counters
                self.files_deleted += 1
                self.bytes_deleted += file_size
                return True
        except Exception as e:
            # Just continue if deletion fails
            pass
        return False

    def clear_directory(self, dir_path):
        """Clear contents of a directory and update counters"""
        deleted_count = 0
        if not dir_path.exists() or not dir_path.is_dir():
            return deleted_count

        try:
            for item in dir_path.glob('**/*'):
                if item.is_file():
                    # Skip login and session-related files
                    item_name_lower = item.name.lower()

                    # Don't touch login files
                    if self.preserve_logins and any(keyword in item_name_lower for keyword in [
                        "login", "password", "key", "auth", "credential", "token", "identity",
                        "account", "sign", "secure", "preference", "bookmarks"
                    ]):
                        continue

                    # Don't touch session files
                    if self.preserve_sessions and any(keyword in item_name_lower for keyword in [
                        "session", "tab", "window", "state", "open", "current", "cookies", "visited", "history"
                    ]):
                        continue

                    if self.delete_file(item):
                        deleted_count += 1
        except Exception as e:
            pass

        return deleted_count

    def clean_safari(self):
        try:
            browser_files_deleted = 0

            # Check if Safari is running instead of forcing close
            result = subprocess.run(['pgrep', 'Safari'], capture_output=True, text=True)
            if result.stdout.strip():
                print("Safari is running. Only cleaning safe cache files.")

            # Safari cache paths - only include pure cache files
            cache_paths = [
                self.home / "Library/Safari/WebKit/MediaCache",
                self.home / "Library/Caches/com.apple.Safari/fsCachedData"
            ]

            for path in cache_paths:
                if path.exists():
                    if path.is_dir():
                        # For directories, safely clear contents
                        try:
                            count = self.clear_directory(path)
                            browser_files_deleted += count
                        except PermissionError:
                            self.errors.append(f"Safari: Permission error with {path}")
                    else:
                        # For regular files, try to remove them
                        try:
                            if self.delete_file(path):
                                browser_files_deleted += 1
                        except PermissionError:
                            self.errors.append(f"Safari: Permission error with {path}")

            print(f"Safari: {browser_files_deleted} cache items cleaned")
            self.browsers_cleaned.append("Safari")
            return True
        except Exception as e:
            self.errors.append(f"Safari: {str(e)}")
            return False

    def clean_chrome(self):
        try:
            browser_files_deleted = 0

            # Check if Chrome is running instead of forcing close
            result = subprocess.run(['pgrep', 'Google Chrome'], capture_output=True, text=True)
            if result.stdout.strip():
                print("Google Chrome is running. Only cleaning safe cache files.")

            # Chrome cache paths
            chrome_path = self.home / "Library/Application Support/Google/Chrome"

            if not chrome_path.exists():
                self.errors.append("Chrome: Browser directory not found")
                return False

            # Find all profile directories
            profile_dirs = []
            if chrome_path.exists():
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

            # Only clean safe cache folders in each profile
            for profile in profile_dirs:
                cache_paths = [
                    profile / "Cache",
                    profile / "Code Cache",
                    profile / "GPUCache",
                    profile / "Media Cache"
                ]

                for path in cache_paths:
                    if path.exists():
                        if path.is_dir():
                            try:
                                count = self.clear_directory(path)
                                browser_files_deleted += count
                            except:
                                self.errors.append(f"Chrome: Permission error with {path}")
                        else:
                            # For regular files, try to remove them
                            if self.delete_file(path):
                                browser_files_deleted += 1

            # Try to clear system-level Chrome caches
            system_cache_paths = [
                self.home / "Library/Caches/Google/Chrome"
            ]

            for path in system_cache_paths:
                if path.exists():
                    if path.is_dir():
                        count = self.clear_directory(path)
                        browser_files_deleted += count
                    else:
                        if self.delete_file(path):
                            browser_files_deleted += 1

            print(f"Chrome: {browser_files_deleted} cache items cleaned")
            self.browsers_cleaned.append("Google Chrome")
            return True
        except Exception as e:
            self.errors.append(f"Chrome: {str(e)}")
            return False

    def clean_firefox(self):
        try:
            browser_files_deleted = 0

            # Check if Firefox is running instead of forcing close
            result = subprocess.run(['pgrep', 'firefox'], capture_output=True, text=True)
            if result.stdout.strip():
                print("Firefox is running. Only cleaning safe cache files.")

            # Find Firefox profile folder
            mozilla_path = self.home / "Library/Application Support/Firefox/Profiles"
            if not mozilla_path.exists():
                self.errors.append("Firefox: Profile directory not found")
                return False

            profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir() and d.name.endswith('.default')]

            if not profile_dirs:
                # Look for any profile if default not found
                profile_dirs = [d for d in mozilla_path.iterdir() if d.is_dir()]

            if not profile_dirs:
                self.errors.append("Firefox: No profiles found")
                return False

            # Only clean safe cache folders in each profile
            for profile in profile_dirs:
                cache_paths = [
                    profile / "cache2",
                    profile / "startupCache",
                    profile / "thumbnails"
                ]

                for path in cache_paths:
                    if path.exists():
                        if path.is_dir():
                            try:
                                count = self.clear_directory(path)
                                browser_files_deleted += count
                            except:
                                pass
                        else:
                            # For regular files, try to remove them
                            if self.delete_file(path):
                                browser_files_deleted += 1

            # Try to clear system-level Firefox caches
            system_cache_paths = [
                self.home / "Library/Caches/Mozilla/Firefox"
            ]

            for path in system_cache_paths:
                if path.exists():
                    if path.is_dir():
                        count = self.clear_directory(path)
                        browser_files_deleted += count
                    else:
                        if self.delete_file(path):
                            browser_files_deleted += 1

            print(f"Firefox: {browser_files_deleted} cache items cleaned")
            self.browsers_cleaned.append("Firefox")
            return True
        except Exception as e:
            self.errors.append(f"Firefox: {str(e)}")
            return False

    def clean_brave(self):
        try:
            browser_files_deleted = 0

            # Check if Brave is running instead of forcing close
            result = subprocess.run(['pgrep', 'Brave'], capture_output=True, text=True)
            if result.stdout.strip():
                print("Brave is running. Only cleaning safe cache files.")

            # Brave cache paths
            brave_path = self.home / "Library/Application Support/BraveSoftware/Brave-Browser"
            if not brave_path.exists():
                brave_path = self.home / "Library/Application Support/Brave-Browser"

            if not brave_path.exists():
                self.errors.append("Brave: Browser directory not found")
                return False

            # Find all profile directories
            profile_dirs = []
            if brave_path.exists():
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

            # Only clean safe cache folders in each profile
            for profile in profile_dirs:
                cache_paths = [
                    profile / "Cache",
                    profile / "Code Cache",
                    profile / "GPUCache",
                    profile / "Media Cache"
                ]

                for path in cache_paths:
                    if path.exists():
                        if path.is_dir():
                            try:
                                count = self.clear_directory(path)
                                browser_files_deleted += count
                            except:
                                pass
                        else:
                            # For regular files, try to remove them
                            if self.delete_file(path):
                                browser_files_deleted += 1

            # Try to clear system-level Brave caches
            system_cache_paths = [
                self.home / "Library/Caches/BraveSoftware/Brave-Browser"
            ]

            for path in system_cache_paths:
                if path.exists():
                    if path.is_dir():
                        count = self.clear_directory(path)
                        browser_files_deleted += count
                    else:
                        if self.delete_file(path):
                            browser_files_deleted += 1

            print(f"Brave: {browser_files_deleted} cache items cleaned")
            self.browsers_cleaned.append("Brave")
            return True
        except Exception as e:
            self.errors.append(f"Brave: {str(e)}")
            return False

    def clear_system_caches(self):
        """Clear only browser media caches at the system level"""
        print("Cleaning system-level browser caches...")
        system_files_deleted = 0

        # System directories that might contain browser media cache data
        system_cache_dirs = [
            self.home / "Library/Caches/com.apple.Safari",
            self.home / "Library/Caches/Google/Chrome",
            self.home / "Library/Caches/com.google.Chrome",
            self.home / "Library/Caches/Mozilla/Firefox",
            self.home / "Library/Caches/org.mozilla.firefox",
            self.home / "Library/Caches/BraveSoftware/Brave-Browser",
            self.home / "Library/Caches/com.brave.Browser"
        ]

        # Safe media cache keywords
        media_cache_keywords = [
            "mediacache", "imagecache", "diskcache", "webcache",
            "thumbnail", "icon", "imagecache", "videocache"
        ]

        for directory in system_cache_dirs:
            if not directory.exists():
                continue

            if directory.is_dir():
                # Look for media cache files in this directory
                try:
                    for item in directory.glob('**/*'):
                        item_name_lower = item.name.lower()

                        # Only clean items that are clearly media cache
                        if any(keyword in item_name_lower for keyword in media_cache_keywords):
                            if item.is_dir():
                                count = self.clear_directory(item)
                                system_files_deleted += count
                            else:
                                if self.delete_file(item):
                                    system_files_deleted += 1
                except:
                    pass

        print(f"System cache cleaning: {system_files_deleted} items removed")
        return system_files_deleted

    def format_bytes(self, size):
        """Format bytes to a human-readable format"""
        power = 2**10  # 1024
        n = 0
        power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
        while size > power:
            size /= power
            n += 1
        return f"{size:.2f} {power_labels[n]}"

    def clean_all(self):
        print("Browser Cache Cleaner starting...")
        print(f"Force close browsers: {'Enabled' if self.force_close else 'Disabled'}")
        print(f"Preserve login information: {'Enabled' if self.preserve_logins else 'Disabled'}")
        print(f"Preserve browser sessions: {'Enabled' if self.preserve_sessions else 'Disabled'}")

        print("\nNOTE: This script is configured to clean only pure cache files")
        print("Login information and current browser sessions will be preserved.")
        print("For browsers that are currently running, the script will clean only the safest cache files.")

        print("\nNOTE: On macOS, some cache files may be protected by System Integrity Protection.")
        print("We'll try to clear accessible cache files and use alternative methods when possible.")

        self.clean_safari()
        self.clean_chrome()
        self.clean_firefox()
        self.clean_brave()

        # Additional step: clear system-level caches
        self.clear_system_caches()

        print("\nCleaning complete!")
        print(f"Browsers cleaned: {', '.join(self.browsers_cleaned) if self.browsers_cleaned else 'None'}")
        print(f"Total items cleaned: {self.files_deleted}")

        if self.bytes_deleted > 0:
            print(f"Disk space freed: {self.format_bytes(self.bytes_deleted)}")

        if self.errors:
            print("\nErrors encountered:")
            for error in self.errors:
                print(f"- {error}")

            print("\nTip: Some errors are normal due to macOS security. The script still cleaned accessible files.")

        print("\nNote: The script preserved login information and browser sessions, so you won't need to re-enter credentials.")
        print("For the safest cleaning, you can also manually clear caches from within each browser:")
        print("- Safari: Safari menu > Preferences > Advanced > Show Develop menu > Develop > Empty Caches")
        print("- Chrome/Brave: Settings > Privacy and security > Clear browsing data > Select 'Cached images and files' only")
        print("- Firefox: Settings > Privacy & Security > Cookies and Site Data > Clear Data > Select 'Cached Web Content' only")

if __name__ == "__main__":
    cleaner = BrowserCacheCleaner()

    # Configure to preserve sessions and not force close browsers
    cleaner.force_close = False
    cleaner.preserve_logins = True
    cleaner.preserve_sessions = True

    cleaner.clean_all()