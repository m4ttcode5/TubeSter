import os
import re
import csv
import sys
import subprocess
import tempfile
from flask import Flask, request, jsonify, send_file, send_from_directory
from dotenv import load_dotenv
import requests

load_dotenv()

app = Flask(__name__, static_folder='web_ui', static_url_path='')

EXPORT_FIELD_MAP = {
    "Title": "%(title)s",
    "URL": "%(webpage_url)s",
    "ID": "%(id)s",
    "Description": "%(description)s",
    "Published Date": "%(upload_date)s",
    "Duration": "%(duration_string)s",
    "Views": "%(view_count)s",
    "Likes": "%(like_count)s",
    "Comments": "%(comment_count)s",
    "Thumbnail URL": "%(thumbnail)s"
}

def extract_channel_name(url):
    patterns = [
        r"youtube\.com/(@[\w.-]+)",
        r"youtube\.com/c/([\w.-]+)",
        r"youtube\.com/user/([\w.-]+)",
        r"youtube\.com/channel/([\w.-]+)"
    ]
    channel_name = None
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            channel_name = match.group(1)
            break

    if not channel_name:
        try:
            path_parts = url.strip('/').split('/')
            last_part = path_parts[-1]
            if last_part and not bool(re.search(r'[=&?]', last_part)) and len(last_part) > 2:
                channel_name = last_part
        except Exception:
            pass

    if channel_name:
        if channel_name.startswith('@'):
            channel_name = channel_name[1:]
        channel_name = re.sub(r'[<>:"/\\|?*]+', '_', channel_name)
        channel_name = re.sub(r'[_ ]+', '_', channel_name).strip('_')
        return channel_name
    else:
        return None

# Define fields available in basic (flat) mode
BASIC_FIELDS = ["Title", "URL", "ID"]

def get_videos_and_save(channel_url, output_dir, output_option, export_fields, search_type="advanced"): # Add search_type parameter
    if not channel_url:
        return "Error: Please provide a Channel URL.", None

    if output_option == "save" and not output_dir:
        return "Error: Please provide an Output Directory.", None

    if not export_fields:
        return "Error: Please select at least one export field.", None

    # Validate fields based on search type
    if search_type == "basic":
        invalid_fields = [field for field in export_fields if field not in BASIC_FIELDS]
        if invalid_fields:
            return f"Error: The following fields are not available in Basic Search: {', '.join(invalid_fields)}. Please select only Title, URL, or ID, or use Advanced Search.", None
        # Filter export_fields to only basic ones for safety, though UI should handle this
        export_fields = [field for field in export_fields if field in BASIC_FIELDS]
        if not export_fields: # Handle case where filtering leaves no fields
             return "Error: Please select at least Title, URL, or ID for Basic Search.", None


    if not re.match(r"https?://(www\.)?youtube\.com/", channel_url, re.IGNORECASE):
        return "Error: Invalid YouTube URL format. Must start with http(s)://youtube.com/", None

    channel_name = extract_channel_name(channel_url)
    if not channel_name:
        return f"Error: Could not extract a usable channel name from the URL: {channel_url}", None

    if output_option == "save":
        # Normalize and validate output directory path
        try:
            output_dir = os.path.normpath(output_dir)
            if not os.path.isabs(output_dir):
                output_dir = os.path.abspath(output_dir)
            print(f"Normalized output directory: {output_dir}")
            
            if not os.path.exists(output_dir):
                print(f"Creating output directory: {output_dir}")
                os.makedirs(output_dir, exist_ok=True)
            
            if not os.access(output_dir, os.W_OK):
                return f"No write permission for output directory: {output_dir}", None
            
            # Create save folder path
            save_folder = os.path.join(output_dir, channel_name)
            print(f"Full save folder path: {save_folder}")
        except Exception as e:
            print(f"Error setting up output directory: {e}")
            return f"Error setting up output directory: {e}", None
    else:
        save_folder = tempfile.mkdtemp()
        print(f"Created temp directory: {save_folder}")

    # Ensure save folder exists
    try:
        os.makedirs(save_folder, exist_ok=True)
        if not os.path.exists(save_folder):
            return f"Failed to create directory: {save_folder}", None
        
        if not os.access(save_folder, os.W_OK):
            return f"No write permission for directory: {save_folder}", None
    except OSError as e:
        return f"Error creating directory '{save_folder}': {e}", None
    except Exception as e:
        return f"Error during directory creation setup '{save_folder}': {e}", None

    # Create CSV file path
    csv_filepath = os.path.join(save_folder, f"{channel_name}_video_list.csv")
    
    # Verify CSV file path is writable
    try:
        with open(csv_filepath, 'a') as f:
            pass
        os.remove(csv_filepath)
    except OSError as e:
        return f"Cannot write to file path '{csv_filepath}': {e}", None

    import json  # ensure json is imported early

    # --- Build yt-dlp command based on search_type ---
    if search_type == "advanced":
        # Step 1: Get flat playlist info to count videos
        flat_command = [
            'yt-dlp',
            '--ignore-errors',
            '--skip-download',
            '--flat-playlist',
            '--dump-single-json',
            channel_url
        ]
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        flat_result = subprocess.run(flat_command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        entries = []
        try:
            flat_json = json.loads(flat_result.stdout)
            entries = flat_json.get('entries', [])
        except Exception:
            entries = []

        total_videos = len(entries)

        if total_videos <= 100:
            # Proceed with original single call
            command = [
                'yt-dlp',
                '--ignore-errors',
                '--skip-download',
                '-J',
                channel_url
            ]
            batch_mode = False
        else:
            # Batch mode
            batch_mode = True
            video_ids = [entry.get('id') for entry in entries if entry and 'id' in entry]
            batches = [video_ids[i:i+100] for i in range(0, total_videos, 100)]

            import concurrent.futures
            all_video_entries = []

            def fetch_batch(batch):
                batch_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in batch]
                batch_command = [
                    'yt-dlp',
                    '--ignore-errors',
                    '--skip-download',
                    '-J'
                ] + batch_urls

                batch_result = subprocess.run(batch_command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

                try:
                    batch_json = json.loads(batch_result.stdout)
                    entries = []
                    if isinstance(batch_json, dict) and 'entries' in batch_json:
                        entries = batch_json['entries']
                    elif isinstance(batch_json, list):
                        entries = batch_json
                    elif isinstance(batch_json, dict):
                        entries = [batch_json]
                    return entries
                except Exception:
                    return []

            # Run batches in parallel
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(fetch_batch, batch) for batch in batches]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        batch_entries = future.result()
                        all_video_entries.extend(batch_entries)
                    except Exception:
                        continue

            # Create a fake playlist_json to reuse existing parsing logic
            playlist_json = {
                'entries': all_video_entries,
                'id': flat_json.get('id'),
                'title': flat_json.get('title'),
                'uploader': flat_json.get('uploader'),
                'uploader_id': flat_json.get('uploader_id'),
                'webpage_url': channel_url
            }
    else: # Basic search
        # Build --print format only for allowed basic fields
        print_format = ";".join(EXPORT_FIELD_MAP[field] for field in export_fields if field in BASIC_FIELDS)
        command = [
            'yt-dlp',
            '--ignore-errors',
            '--skip-download',
            '--flat-playlist', # Use flat playlist for speed
            '--print', print_format,
            channel_url
        ]
        batch_mode = False
    # --- End command building ---

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        video_data = []
        json_keys_map = {
            "Title": "title",
            "URL": "webpage_url",
            "ID": "id",
            "Description": "description",
            "Published Date": "upload_date",
            "Duration": "duration_string",
            "Views": "view_count",
            "Likes": "like_count",
            "Comments": "comment_count",
            "Thumbnail URL": "thumbnail"
        }

        if search_type == "advanced":
            if not batch_mode:
                result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

                if result.returncode != 0:
                    print(f"Warning: yt-dlp exited with code {result.returncode}")
                    print(f"yt-dlp stderr: {result.stderr}")

                if not result.stdout and result.stderr:
                    return f"Error: yt-dlp failed.\nstderr: {result.stderr}", None
                elif not result.stdout:
                    return f"Error: yt-dlp produced no output. Check channel URL and yt-dlp installation. Stderr: {result.stderr}", None

                try:
                    playlist_json = json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    print(f"Error: Failed to decode JSON output from yt-dlp (Advanced): {e}. Output: '{result.stdout[:200]}...'")
                    return f"Error: Failed to parse yt-dlp output as JSON. Stderr: {result.stderr}", None
                except Exception as e:
                    print(f"Error processing JSON data (Advanced): {e}")
                    return f"Error processing yt-dlp JSON data: {e}", None
            # else: batch_mode already has playlist_json prepared

            try:
                if 'entries' in playlist_json and isinstance(playlist_json['entries'], list):
                    for video_json in playlist_json['entries']:
                        if not video_json:
                            continue
                        row_data = {}
                        for field_name in export_fields:
                            json_key = json_keys_map.get(field_name)
                            row_data[field_name] = video_json.get(json_key, '') if json_key else ''
                        video_data.append(row_data)
                elif isinstance(playlist_json, dict):
                    row_data = {}
                    for field_name in export_fields:
                        json_key = json_keys_map.get(field_name)
                        row_data[field_name] = playlist_json.get(json_key, '') if json_key else ''
                    video_data.append(row_data)
                else:
                    print(f"Warning: Unexpected JSON structure from yt-dlp (Advanced).")
            except Exception as e:
                print(f"Error processing JSON data (Advanced): {e}")
                return f"Error processing yt-dlp JSON data: {e}", None

        else:
            # Basic search: run yt-dlp and parse plain text output
            result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

            if result.returncode != 0:
                print(f"Warning: yt-dlp exited with code {result.returncode}")
                print(f"yt-dlp stderr: {result.stderr}")

            if not result.stdout and result.stderr:
                return f"Error: yt-dlp failed.\nstderr: {result.stderr}", None
            elif not result.stdout:
                return f"Error: yt-dlp produced no output. Check channel URL and yt-dlp installation. Stderr: {result.stderr}", None

            output_lines = result.stdout.strip().split('\n')
            current_export_fields = [field for field in export_fields if field in BASIC_FIELDS]
            for line in output_lines:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(';')
                if len(parts) == len(current_export_fields):
                    video_data.append(dict(zip(current_export_fields, parts)))
                else:
                    print(f"Warning: Skipping line due to unexpected number of parts (Basic). Expected {len(current_export_fields)}, got {len(parts)}. Line: '{line[:100]}...'")

        if not video_data:
            stderr_info = ""
            if search_type == "advanced" and not batch_mode and 'result' in locals():
                stderr_info = f"\nstderr: {result.stderr}" if result.stderr else ""
            elif search_type == "basic" and 'result' in locals():
                stderr_info = f"\nstderr: {result.stderr}" if result.stderr else ""
            return f"Warning: No valid video data extracted. yt-dlp output might be empty or in an unexpected format.{stderr_info}", None

        # Write data to CSV file
        print(f"Writing CSV file to: {csv_filepath}")  # Debug log
        os.makedirs(os.path.dirname(csv_filepath), exist_ok=True)  # Ensure directory exists

        try:
            with open(csv_filepath, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=export_fields)
                writer.writeheader()
                writer.writerows(video_data)
            
            # Verify file was written successfully
            if not os.path.exists(csv_filepath):
                return f"Error: File was not created at '{csv_filepath}'", None
            
            if os.path.getsize(csv_filepath) == 0:
                return f"Error: File was created but is empty at '{csv_filepath}'", None
                
            print(f"Successfully wrote {len(video_data)} rows to {csv_filepath}")  # Debug log
            
        except IOError as e:
            print(f"IOError writing CSV: {e}")  # Debug log
            return f"Error writing to CSV file '{csv_filepath}': {e}", None
        except Exception as e:
            print(f"Unexpected error writing CSV: {e}")  # Debug log
            return f"An unexpected error occurred during CSV writing: {e}", None

        if output_option == "save":
            return f"Success! {len(video_data)} videos saved to: {csv_filepath}", csv_filepath
        else:
            # For download mode, return absolute path
            abs_path = os.path.abspath(csv_filepath)
            return f"Success! {len(video_data)} videos ready for download.", abs_path

    except FileNotFoundError:
        return "Error: 'yt-dlp' command not found. Make sure yt-dlp is installed and in your system's PATH.", None
    except subprocess.CalledProcessError as e:
        return f"Error executing yt-dlp: {e}\nstderr: {e.stderr}", None
    except Exception as e:
        import traceback
        print(f"Unexpected error during subprocess execution: {traceback.format_exc()}")
        return f"An unexpected error occurred during processing: {e}", None

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/get_video_ids', methods=['POST'])
def get_video_ids():
    data = request.get_json()
    channel_url = data.get('channel_url')

    if not channel_url:
        return jsonify({'error': 'Missing channel_url'}), 400

    flat_command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '--flat-playlist',
        '--dump-single-json',
        channel_url
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        result = subprocess.run(flat_command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        if result.returncode != 0:
            return jsonify({'error': f'yt-dlp failed: {result.stderr}'}), 500

        import json
        flat_json = json.loads(result.stdout)
        entries = flat_json.get('entries', [])
        video_ids = [entry.get('id') for entry in entries if entry and 'id' in entry]

        return jsonify({'video_ids': video_ids})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/get_video_metadata', methods=['POST'])
def get_video_metadata():
    data = request.get_json()
    video_ids = data.get('video_ids', [])
    export_fields = data.get('export_fields', ["Title", "URL"])

    if not video_ids or not isinstance(video_ids, list):
        return jsonify({'error': 'Missing or invalid video_ids'}), 400

    # Build URLs
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

    command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '-J'
    ] + urls

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        import json
        try:
            batch_json = json.loads(result.stdout)
        except json.JSONDecodeError:
            # If no output at all, treat as empty batch
            if not result.stdout.strip():
                return jsonify({'videos': []})
            # If parsing fails, but stderr contains known errors, treat as empty batch
            if "Video unavailable" in result.stderr or "This video is private" in result.stderr:
                return jsonify({'videos': []})
            # Otherwise, return error with raw output for debugging
            return jsonify({'error': f'Failed to parse yt-dlp output.\nstdout: {result.stdout}\nstderr: {result.stderr}'}), 500

        json_keys_map = {
            "Title": "title",
            "URL": "webpage_url",
            "ID": "id",
            "Description": "description",
            "Published Date": "upload_date",
            "Duration": "duration_string",
            "Views": "view_count",
            "Likes": "like_count",
            "Comments": "comment_count",
            "Thumbnail URL": "thumbnail"
        }

        video_data = []

        if isinstance(batch_json, dict) and 'entries' in batch_json:
            entries = batch_json['entries']
        elif isinstance(batch_json, list):
            entries = batch_json
        elif isinstance(batch_json, dict):
            entries = [batch_json]
        else:
            entries = []

        for video_json in entries:
            if not video_json:
                continue
            row_data = {}
            for field_name in export_fields:
                json_key = json_keys_map.get(field_name)
                row_data[field_name] = video_json.get(json_key, '') if json_key else ''
            video_data.append(row_data)

        return jsonify({'videos': video_data})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

@app.route('/get_metadata_api', methods=['POST'])
def get_metadata_api():
    data = request.get_json()
    video_ids = data.get('video_ids', [])
    export_fields = data.get('export_fields', ["Title", "URL"])
    fetch_method = data.get('fetch_method', 'youtube-api')
    api_key = data.get('api_key') or os.getenv("YOUTUBE_API_KEY", "")

    if not video_ids or not isinstance(video_ids, list):
        return jsonify({'error': 'Missing or invalid video_ids'}), 400

    if fetch_method == 'yt-dlp':
        # Use yt-dlp fallback
        urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
        command = [
            'yt-dlp',
            '--ignore-errors',
            '--skip-download',
            '-J'
        ] + urls

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

            import json
            try:
                batch_json = json.loads(result.stdout)
            except json.JSONDecodeError:
                return jsonify({'videos': []})

            json_keys_map = {
                "Title": "title",
                "URL": "webpage_url",
                "ID": "id",
                "Description": "description",
                "Published Date": "upload_date",
                "Duration": "duration_string",
                "Views": "view_count",
                "Likes": "like_count",
                "Comments": "comment_count",
                "Thumbnail URL": "thumbnail"
            }

            video_data = []

            if isinstance(batch_json, dict) and 'entries' in batch_json:
                entries = batch_json['entries']
            elif isinstance(batch_json, list):
                entries = batch_json
            elif isinstance(batch_json, dict):
                entries = [batch_json]
            else:
                entries = []

            for video_json in entries:
                if not video_json:
                    continue
                row_data = {}
                for field_name in export_fields:
                    json_key = json_keys_map.get(field_name)
                    row_data[field_name] = video_json.get(json_key, '') if json_key else ''
                video_data.append(row_data)

            return jsonify({'videos': video_data})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # Else, use YouTube API
    # Process videos in smaller batches
    BATCH_SIZE = 10
    videos = []
    
    try:
        for i in range(0, len(video_ids), BATCH_SIZE):
            batch = video_ids[i:i + BATCH_SIZE]
            ids_str = ",".join(batch)
            
            url = "https://www.googleapis.com/youtube/v3/videos"
            params = {
                "part": "snippet,contentDetails,statistics",
                "id": ids_str,
                "key": api_key
            }

            try:
                if not api_key:
                    return jsonify({'error': 'Missing YouTube API key. Please check your environment variables.'}), 400

                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                
                if 'error' in data:
                    error_msg = data['error'].get('message', 'Unknown error')
                    error_code = data['error'].get('code', 'unknown')
                    if error_code == 403:
                        print(f"YouTube API Quota Exceeded or Access Denied: {error_msg}")
                        return jsonify({'error': f"YouTube API Error: {error_msg}. Please check your quota limits and API key permissions."}), 403
                    else:
                        print(f"YouTube API Error ({error_code}): {error_msg}")
                        continue

                # Process each video in the batch
                for item in data.get("items", []):
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    content = item.get("contentDetails", {})
                    video = {}

                    import isodate

                    for field in export_fields:
                        if field == "Title":
                            video[field] = snippet.get("title", "")
                        elif field == "URL":
                            video[field] = f"https://www.youtube.com/watch?v={item.get('id','')}"
                        elif field == "ID":
                            video[field] = item.get("id", "")
                        elif field == "Description":
                            video[field] = snippet.get("description", "")
                        elif field == "Published Date":
                            video[field] = snippet.get("publishedAt", "")
                        elif field == "Duration":
                            iso_duration = content.get("duration", "")
                            try:
                                duration_seconds = int(isodate.parse_duration(iso_duration).total_seconds())
                                hours = duration_seconds // 3600
                                minutes = (duration_seconds % 3600) // 60
                                seconds = duration_seconds % 60
                                if hours > 0:
                                    video[field] = f"{hours}:{minutes:02}:{seconds:02}"
                                else:
                                    video[field] = f"{minutes}:{seconds:02}"
                            except:
                                video[field] = iso_duration
                        elif field == "Views":
                            video[field] = stats.get("viewCount", "")
                        elif field == "Likes":
                            video[field] = stats.get("likeCount", "")
                        elif field == "Comments":
                            video[field] = stats.get("commentCount", "")
                        elif field == "Thumbnail URL":
                            thumbs = snippet.get("thumbnails", {})
                            video[field] = thumbs.get("high", {}).get("url", "")
                        else:
                            video[field] = ""
                    videos.append(video)

            except requests.RequestException as e:
                print(f"Error fetching batch {i//BATCH_SIZE + 1}: {str(e)}")
                continue

        return jsonify({'videos': videos})

    except Exception as e:
        return jsonify({'error': f"API Error: {str(e)} - Please check your YouTube API key and quota limits"}), 500


@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    channel_url = data.get('channel_url')
    output_dir = data.get('output_dir')
    output_option = data.get('output_option', 'save')
    export_fields = data.get('export_fields', ["Title", "URL"])
    search_type = data.get('search_type', 'advanced')

    print(f"Download request: option={output_option}, dir={output_dir}")  # Debug log

    message, csv_path = get_videos_and_save(channel_url, output_dir, output_option, export_fields, search_type)
    print(f"get_videos_and_save returned: message={message}, path={csv_path}")  # Debug log

    if not message.startswith("Success"):
        return jsonify({'message': message}), 400

    # Always return the path for both save and download modes
    if csv_path and os.path.exists(csv_path):
        abs_path = os.path.abspath(csv_path)
        return jsonify({
            'message': message,
            'csv_path': abs_path
        })
    else:
        error_msg = f"File not found at expected location: {csv_path}"
        print(error_msg)  # Debug log
        return jsonify({'message': error_msg}), 500

@app.route('/select_folder', methods=['GET'])
def select_folder():
    import tkinter as tk
    from tkinter import filedialog
    try:
        # Initialize Tkinter without showing window
        root = tk.Tk()
        root.withdraw()
        
        # Ensure window stays hidden and appears on top
        root.attributes('-topmost', True)
        
        if sys.platform == "win32":
            import win32gui
            import win32con
            # Additional Windows-specific handling
            # Get the Windows handle of the Tkinter window
            hwnd = win32gui.GetForegroundWindow()
            # Move window off screen
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            # Fix focus issues on Windows
            root.wm_attributes('-topmost', 1)
            root.focus_force()
        
        # Show folder selection dialog with initial directory
        initial_dir = os.path.expanduser("~")
        folder_path = filedialog.askdirectory(
            title="Select Output Folder",
            parent=root,
            initialdir=initial_dir
        )
        
        # Clean up Tkinter
        root.quit()
        root.destroy()
        
        # Convert path to proper format for OS
        if folder_path:
            folder_path = os.path.normpath(folder_path)
            return jsonify({'path': folder_path})
        return jsonify({'path': ''})
        
    except Exception as e:
        print(f"Error opening folder dialog: {str(e)}")
        error_msg = str(e)
        if "win32gui" in error_msg:
            # Fallback if win32gui is not available
            return select_folder_fallback()
        return jsonify({'error': 'Failed to open folder selection dialog', 'details': error_msg}), 500

def select_folder_fallback():
    """Fallback method for folder selection when win32gui is not available"""
    import tkinter as tk
    from tkinter import filedialog
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        initial_dir = os.path.expanduser("~")
        folder_path = filedialog.askdirectory(
            title="Select Output Folder",
            initialdir=initial_dir
        )
        root.destroy()
        if folder_path:
            return jsonify({'path': os.path.normpath(folder_path)})
        return jsonify({'path': ''})
    except Exception as e:
        return jsonify({'error': 'Folder selection failed', 'details': str(e)}), 500

from flask import send_file, request as flask_request

@app.route('/download_csv')
def download_csv():
    csv_path = flask_request.args.get('path')
    print(f"Download request for file: {csv_path}")  # Debug log

    if not csv_path:
        print("Error: No path provided")  # Debug log
        return "No file path provided", 400

    if not os.path.isfile(csv_path):
        print(f"Error: File not found at {csv_path}")  # Debug log
        return "File not found", 404

    try:
        print(f"Sending file: {csv_path}")  # Debug log
        # Use absolute path and mime type
        abs_path = os.path.abspath(csv_path)
        return send_file(
            abs_path,
            as_attachment=True,
            mimetype='text/csv',
            download_name=os.path.basename(csv_path)
        )
    except Exception as e:
        print(f"Error sending file: {e}")  # Debug log
        return f"Error sending file: {e}", 500

if __name__ == '__main__':
    app.run(debug=True)
