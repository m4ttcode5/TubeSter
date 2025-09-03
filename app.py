import os
import re
import csv
import sys
import subprocess
import tempfile
import json
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

# Define fields available in basic (flat) mode
BASIC_FIELDS = ["Title", "URL", "ID"]

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

def normalize_channel_url(url):
    """Ensure the YouTube channel URL has /videos suffix for yt-dlp compatibility"""
    if not url:
        return url

    # Remove any trailing slash
    url = url.rstrip('/')

    # If it's already a video URL or has /videos, return as is
    if '/watch?' in url or '/videos' in url:
        return url

    # For channel URLs, append /videos
    if 'youtube.com/@' in url or 'youtube.com/c/' in url or 'youtube.com/user/' in url or 'youtube.com/channel/' in url:
        return url + '/videos'

    # For handle format (@username), convert to full URL with /videos
    if url.startswith('@'):
        return f'https://www.youtube.com/{url}/videos'

    return url

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/download_csv')
def download_csv():
    csv_path = request.args.get('path')
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

@app.route('/select_folder', methods=['GET'])
def select_folder():
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

# Mapping from user-friendly field names to YouTube API parts and paths
API_FIELD_MAP = {
    "Title": {"part": "snippet", "path": "snippet.title"},
    "URL": {"part": "id", "path": "id", "transform": lambda vid: f"https://www.youtube.com/watch?v={vid}"},
    "ID": {"part": "id", "path": "id"},
    "Description": {"part": "snippet", "path": "snippet.description"},
    "Published Date": {"part": "snippet", "path": "snippet.publishedAt", "transform": lambda dt: dt.split('T')[0] if dt else ''}, # Extract date part
    "Duration": {"part": "contentDetails", "path": "contentDetails.duration", "transform": lambda pd: isoduration_to_string(pd)}, # Convert ISO 8601 duration
    "Views": {"part": "statistics", "path": "statistics.viewCount"},
    "Likes": {"part": "statistics", "path": "statistics.likeCount"},
    "Comments": {"part": "statistics", "path": "statistics.commentCount"},
    "Thumbnail URL": {"part": "snippet", "path": "snippet.thumbnails.high.url"} # Or default/medium
}

# Helper to convert ISO 8601 duration (e.g., PT1M30S) to H:MM:SS or MM:SS
def isoduration_to_string(duration_iso):
    if not duration_iso or not duration_iso.startswith('PT'):
        return ''
    
    duration_iso = duration_iso[2:] # Remove PT
    hours, minutes, seconds = 0, 0, 0
    
    if 'H' in duration_iso:
        parts = duration_iso.split('H')
        hours = int(parts[0])
        duration_iso = parts[1]
    if 'M' in duration_iso:
        parts = duration_iso.split('M')
        minutes = int(parts[0])
        duration_iso = parts[1]
    if 'S' in duration_iso:
        seconds = int(duration_iso.replace('S', ''))

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"

# Helper to get nested dictionary value
def get_nested_value(data_dict, path_string):
    keys = path_string.split('.')
    value = data_dict
    try:
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None # Path broken
        return value
    except Exception:
        return None


def get_metadata_yt_dlp(normalized_url, export_fields):
    """Get video metadata using yt-dlp as fallback when API is not available or fails"""
    command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '--dump-single-json',
        normalized_url
    ]

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)

        if result.returncode != 0:
            print(f"yt-dlp command failed: {result.stderr}")
            return None

        data = json.loads(result.stdout)
        videos = data.get('entries', [])
        video_data = []

        for video in videos:
            if not video or not isinstance(video, dict):
                continue

            row = {}
            for field in export_fields:
                if field in EXPORT_FIELD_MAP:
                    format_str = EXPORT_FIELD_MAP[field]
                    try:
                        value = format_str % video
                        row[field] = value
                    except (KeyError, TypeError, ValueError):
                        row[field] = ''
                else:
                    row[field] = ''
            video_data.append(row)

        return video_data

    except Exception as e:
        print(f"Error in get_metadata_yt_dlp: {str(e)}")
        return None

def get_videos_and_save(channel_url, output_dir, output_option, export_fields, search_type="advanced", api_key=""):
    if not channel_url:
        return "Error: Please provide a Channel URL.", None

    if output_option == "save" and not output_dir:
        return "Error: Please provide an Output Directory.", None

    if not export_fields:
        return "Error: Please select at least one export field.", None

    if search_type == "basic":
        invalid_fields = [field for field in export_fields if field not in BASIC_FIELDS]
        # Basic search is deprecated when using API, as API always gives more fields
        # We might re-introduce a simplified field selection later if needed.
        pass # Keep all requested fields for API search

    # API key is optional; if not provided, will use yt-dlp for metadata

    # Normalize the URL for better yt-dlp compatibility
    normalized_url = normalize_channel_url(channel_url)

    channel_name = extract_channel_name(channel_url)
    if not channel_name:
        # Try a default name if extraction fails but URL might still work for yt-dlp
        channel_name = "youtube_channel"
        print(f"Warning: Could not extract channel name from URL: {channel_url}. Using default name '{channel_name}'.")
        # return f"Error: Could not extract a usable channel name from the URL: {channel_url}", None

    if output_option == "save":
        try:
            output_dir = os.path.normpath(output_dir)
            if not os.path.isabs(output_dir):
                output_dir = os.path.abspath(output_dir)
            
            if not os.path.exists(output_dir):
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    print(f"Successfully created directory: {output_dir}")
                except Exception as e:
                    error_message = f"Error creating output directory: {e}"
                    print(error_message)
                    return error_message, None
            else:
                print(f"Output directory already exists: {output_dir}")

            save_folder = os.path.join(output_dir, channel_name)
            # Ensure save folder exists
            try:
                os.makedirs(save_folder, exist_ok=True)
                print(f"Successfully created save folder: {save_folder}")
                if not os.access(save_folder, os.W_OK):
                    error_message = f"Error: No write permission for directory: {save_folder}"
                    print(error_message)
                    return error_message, None
            except Exception as e:
                error_message = f"Error creating directory '{save_folder}': {e}"
                print(error_message)
                return error_message, None

        except Exception as e: # This except belongs to the outer try block starting at line 189
            error_message = f"Error setting up output directory: {e}"
            print(error_message)
            return error_message, None
    else: # download option
        try:
            save_folder = tempfile.mkdtemp()
            print(f"Successfully created temporary directory: {save_folder}")
        except Exception as e:
            error_message = f"Error creating temporary directory: {e}"
            print(error_message)
            return error_message, None


    # Create CSV file path (moved outside the try/except for directory setup)
    try:
        csv_filepath = os.path.join(save_folder, f"{channel_name}_video_list.csv")
    except Exception as e:
         # Handle potential errors if save_folder wasn't created properly
         error_message = f"Error defining CSV file path: {e}"
         print(error_message)
         return error_message, None

    # --- Step 1: Get Video IDs using yt-dlp (flat list) ---
    id_command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '--flat-playlist',
        '--print', '%(id)s', # Print only video IDs
        normalized_url
    ]
    video_ids = []
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # startupinfo.wShowWindow = subprocess.SW_HIDE # Keep visible for debugging if needed

        print(f"Running yt-dlp to get video IDs: {' '.join(id_command)}") # Debug log
        result = subprocess.run(id_command, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo, check=False) # check=False allows us to see stderr

        if result.returncode != 0:
             # Check stderr for the specific bot error, even if IDs were partially extracted
            if "Sign in to confirm" in result.stderr:
                 print(f"Warning: yt-dlp encountered 'Sign in' error but might have extracted some IDs. Stderr: {result.stderr}")
                 # Proceed if some IDs were found, otherwise fail
            elif result.stderr:
                 print(f"Warning: yt-dlp command for IDs finished with errors. Stderr: {result.stderr}")
                 # Proceed if some IDs were found, otherwise fail

        if result.stdout:
            video_ids = result.stdout.strip().split('\n')
            video_ids = [vid for vid in video_ids if vid] # Remove empty lines
            print(f"Found {len(video_ids)} video IDs via yt-dlp.")
        
        if not video_ids:
             # If no IDs found AND there was an error, report it
             if result.returncode != 0 and result.stderr:
                 return f"Error: yt-dlp failed to retrieve video IDs. Stderr: {result.stderr}", None
             else:
                 return f"Error: No video IDs found for the given URL using yt-dlp.", None

    except Exception as e:
        return f"Error running yt-dlp to get video IDs: {str(e)}", None

    # --- Step 2: Fetch Metadata ---
    video_data = []

    if api_key:
        # Try using YouTube Data API v3
        BATCH_SIZE = 50 # API limit per request

        # Determine required API parts based on selected fields
        required_parts = set(['id']) # ID is always needed for URL construction if requested
        for field in export_fields:
            if field in API_FIELD_MAP:
                required_parts.add(API_FIELD_MAP[field]['part'])
        parts_str = ",".join(list(required_parts))

        print(f"Fetching metadata for {len(video_ids)} videos using API parts: {parts_str}")

        use_yt_dlp = False
        try:
            for i in range(0, len(video_ids), BATCH_SIZE):
                batch_ids = video_ids[i:i + BATCH_SIZE]
                ids_str = ",".join(batch_ids)

                api_url = "https://www.googleapis.com/youtube/v3/videos"
                params = {
                    "part": parts_str,
                    "id": ids_str,
                    "key": api_key
                }

                print(f"Calling YouTube API for batch {i//BATCH_SIZE + 1}...") # Debug log
                resp = requests.get(api_url, params=params, timeout=20) # Increased timeout
                if resp.status_code == 400:
                    try:
                        api_data = resp.json()
                        if 'error' in api_data:
                            error_details = api_data['error']
                            error_msg = error_details.get('message', 'Bad Request')
                            if 'key' in error_msg.lower() or 'invalid' in error_msg.lower():
                                print("API key invalid, falling back to yt-dlp")
                                use_yt_dlp = True
                                break
                            else:
                                return f"Error: YouTube API Error: {error_msg}", None
                    except:
                        pass
                    return f"Error: Bad Request to YouTube API (status 400)", None
                resp.raise_for_status() # Raise HTTPError for other bad responses
                api_data = resp.json()

                if 'error' in api_data:
                    error_details = api_data['error']
                    # Check for specific quota error
                    if error_details.get('errors') and any(e.get('reason') == 'quotaExceeded' for e in error_details['errors']):
                         return f"Error: YouTube API Quota Exceeded. Please check your Google Cloud Console.", None
                    else:
                        error_msg = error_details.get('message', 'Unknown API error')
                        if 'key' in error_msg.lower() or 'invalid' in error_msg.lower():
                            print("API key invalid, falling back to yt-dlp")
                            use_yt_dlp = True
                            break
                        else:
                            return f"Error: YouTube API Error: {error_msg}", None

                if 'items' not in api_data:
                     print(f"Warning: API response for batch {i//BATCH_SIZE + 1} missing 'items'. Response: {api_data}")
                     continue # Skip this batch if no items found

                for item in api_data.get('items', []):
                    row = {}
                    for field in export_fields:
                        if field in API_FIELD_MAP:
                            map_info = API_FIELD_MAP[field]
                            raw_value = get_nested_value(item, map_info['path'])

                            # Apply transformation if defined (e.g., for URL, Duration, Date)
                            if 'transform' in map_info:
                                row[field] = map_info['transform'](raw_value) if raw_value is not None else ''
                            else:
                                row[field] = raw_value if raw_value is not None else ''
                        else:
                            row[field] = '' # Field not supported by API or map
                    video_data.append(row)

            if use_yt_dlp:
                video_data = get_metadata_yt_dlp(normalized_url, export_fields)
                if video_data is None:
                    return "Error: Failed to get metadata from yt-dlp after API key error", None

            print(f"Successfully fetched metadata for {len(video_data)} videos.")

        except requests.exceptions.RequestException as e:
            print(f"API request failed, falling back to yt-dlp: {str(e)}")
            video_data = get_metadata_yt_dlp(normalized_url, export_fields)
            if video_data is None:
                return f"Error: Failed to get metadata from both API and yt-dlp: {str(e)}", None
        except Exception as e:
            # Catch other potential errors during API processing
            import traceback
            print(f"Unexpected error during API processing: {traceback.format_exc()}")
            video_data = get_metadata_yt_dlp(normalized_url, export_fields)
            if video_data is None:
                return f"Error: Failed to get metadata from yt-dlp after API error: {str(e)}", None
    else:
        # No API key provided, use yt-dlp
        print("No API key provided, using yt-dlp for metadata")
        video_data = get_metadata_yt_dlp(normalized_url, export_fields)
        if video_data is None:
            return "Error: Failed to get metadata from yt-dlp", None

    # --- Step 3: Write to CSV ---
    if not video_data:
        return "Warning: No video metadata could be fetched using the API, although IDs were found. The CSV file will be empty or contain only headers.", None

    try:
        print(f"Writing {len(video_data)} rows to CSV: {csv_filepath}")
        with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
            # Ensure fieldnames match the requested export_fields order
            writer = csv.DictWriter(f, fieldnames=export_fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(video_data)
    except Exception as e:
        return f"Error writing CSV file: {e}", None

    # --- Step 4: Return result ---
    if output_option == "save":
        return f"Success! {len(video_data)} videos saved to: {csv_filepath}", csv_filepath
    else: # download option
        abs_path = os.path.abspath(csv_filepath)
        return f"Success! {len(video_data)} videos ready for download.", abs_path

# Removed the misplaced 'except Exception as e:' block from here, as errors are handled within steps

@app.route('/get_video_ids', methods=['POST'])
def get_video_ids():
    data = request.get_json()
    channel_url = data.get('channel_url')

    if not channel_url:
        return jsonify({'error': 'Missing channel_url'}), 400

    # Normalize the URL to ensure /videos suffix for better yt-dlp compatibility
    normalized_url = normalize_channel_url(channel_url)

    command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '--flat-playlist',
        '--dump-single-json',
        normalized_url
    ]

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', startupinfo=startupinfo)
        data = json.loads(result.stdout)
        videos = data.get('entries', [])
        video_ids = [v.get('id') for v in videos if v and 'id' in v]
        
        return jsonify({'video_ids': video_ids})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

@app.route('/get_metadata_api', methods=['POST'])
def get_metadata_api():
    data = request.get_json()
    video_ids = data.get('video_ids', [])
    export_fields = data.get('export_fields', ["Title", "URL"])
    # Assign api_key here, ensuring it's available for the API path
    api_key = data.get('api_key') or os.getenv("YOUTUBE_API_KEY", "")

    if not video_ids or not isinstance(video_ids, list):
        return jsonify({'error': 'Missing or invalid video_ids'}), 400

    # Use YouTube API (yt-dlp fallback removed)
    if not api_key:
        return jsonify({'error': 'Missing YouTube API key'}), 400

    videos = []
    BATCH_SIZE = 50  # YouTube API allows up to 50 IDs per request
    
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

            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 400:
                try:
                    data = resp.json()
                    if 'error' in data:
                        error_msg = data['error'].get('message', 'Bad Request')
                        return jsonify({'error': f"YouTube API Error: {error_msg}"}), 400
                except:
                    pass
                return jsonify({'error': 'Bad Request to YouTube API'}), 400
            resp.raise_for_status()
            data = resp.json()

            if 'error' in data:
                error_msg = data['error'].get('message', 'Unknown error')
                return jsonify({'error': f"YouTube API Error: {error_msg}"}), 500

            for item in data.get('items', []):
                video = {}
                for field in export_fields:
                    if field == "Title":
                        video[field] = item.get('snippet', {}).get('title', '')
                    elif field == "URL":
                        video[field] = f"https://www.youtube.com/watch?v={item.get('id','')}"
                    elif field == "ID":
                        video[field] = item.get('id', '')
                    # Add other fields as needed
                videos.append(video)

        return jsonify({'videos': videos})

    except requests.RequestException as e:
        return jsonify({'error': f"API Error: {str(e)}"}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    channel_url = data.get('channel_url')
    output_dir = data.get('output_dir')
    output_option = data.get('output_option', 'save') # 'save' or 'download'
    export_fields = data.get('export_fields', ["Title", "URL"]) # List of field names
    # search_type = data.get('search_type', 'advanced') # No longer needed as we always use API
    api_key = data.get('api_key') or os.getenv("YOUTUBE_API_KEY", "") # Get key from request or .env

    print(f"Download request: channel='{channel_url}', option='{output_option}', fields={export_fields}, output_dir='{output_dir}'") # Debug log

    # Call the refactored function, passing the API key
    message, csv_path = get_videos_and_save(
        channel_url=channel_url,
        output_dir=output_dir,
        output_option=output_option,
        export_fields=export_fields,
        api_key=api_key
        # search_type is removed
    )
    print(f"get_videos_and_save returned: message='{message}', path='{csv_path}'") # Debug log

    # Check for success or warning messages explicitly
    if not message.startswith("Success") and not message.startswith("Warning"):
        return jsonify({'message': message}), 400

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

def run_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    run_server()
