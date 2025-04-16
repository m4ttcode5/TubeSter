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

def get_videos_and_save(channel_url, output_dir, output_option, export_fields, search_type="advanced"):
    if not channel_url:
        return "Error: Please provide a Channel URL.", None

    if output_option == "save" and not output_dir:
        return "Error: Please provide an Output Directory.", None

    if not export_fields:
        return "Error: Please select at least one export field.", None

    if search_type == "basic":
        invalid_fields = [field for field in export_fields if field not in BASIC_FIELDS]
        if invalid_fields:
            return f"Error: The following fields are not available in Basic Search: {', '.join(invalid_fields)}. Please select only Title, URL, or ID, or use Advanced Search.", None
        export_fields = [field for field in export_fields if field in BASIC_FIELDS]
        if not export_fields:
            return "Error: Please select at least Title, URL, or ID for Basic Search.", None

    channel_name = extract_channel_name(channel_url)
    if not channel_name:
        return f"Error: Could not extract a usable channel name from the URL: {channel_url}", None

    if output_option == "save":
        try:
            output_dir = os.path.normpath(output_dir)
            if not os.path.isabs(output_dir):
                output_dir = os.path.abspath(output_dir)
            
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            if not os.access(output_dir, os.W_OK):
                return f"No write permission for output directory: {output_dir}", None
            
            save_folder = os.path.join(output_dir, channel_name)
        except Exception as e:
            return f"Error setting up output directory: {e}", None
    else:
        save_folder = tempfile.mkdtemp()

    # Create CSV file path
    csv_filepath = os.path.join(save_folder, f"{channel_name}_video_list.csv")
    
    # Ensure save folder exists
    try:
        os.makedirs(save_folder, exist_ok=True)
        if not os.access(save_folder, os.W_OK):
            return f"No write permission for directory: {save_folder}", None
    except Exception as e:
        return f"Error creating directory '{save_folder}': {e}", None

    command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '-J',  # Output JSON
        channel_url
    ]

    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
        
        if result.returncode != 0:
            return f"Error: yt-dlp command failed. {result.stderr}", None

        import json
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            return f"Error parsing yt-dlp output: {e}", None

        video_data = []
        if 'entries' in data:
            for entry in data['entries']:
                if not entry:
                    continue
                row = {}
                for field in export_fields:
                    if field == "Title":
                        row[field] = entry.get('title', '')
                    elif field == "URL":
                        row[field] = entry.get('webpage_url', '')
                    elif field == "ID":
                        row[field] = entry.get('id', '')
                    # Add other fields as needed
                video_data.append(row)

        # Write to CSV
        try:
            with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=export_fields)
                writer.writeheader()
                writer.writerows(video_data)
        except Exception as e:
            return f"Error writing CSV file: {e}", None

        if output_option == "save":
            return f"Success! {len(video_data)} videos saved to: {csv_filepath}", csv_filepath
        else:
            abs_path = os.path.abspath(csv_filepath)
            return f"Success! {len(video_data)} videos ready for download.", abs_path

    except Exception as e:
        return f"Error: {str(e)}", None

@app.route('/get_video_ids', methods=['POST'])
def get_video_ids():
    data = request.get_json()
    channel_url = data.get('channel_url')

    if not channel_url:
        return jsonify({'error': 'Missing channel_url'}), 400

    command = [
        'yt-dlp',
        '--ignore-errors',
        '--skip-download',
        '--flat-playlist',
        '--dump-single-json',
        channel_url
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

        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', startupinfo=startupinfo)
            batch_json = json.loads(result.stdout)
            
            video_data = []
            if isinstance(batch_json, dict) and 'entries' in batch_json:
                entries = batch_json['entries']
            elif isinstance(batch_json, list):
                entries = batch_json
            elif isinstance(batch_json, dict):
                entries = [batch_json]
            else:
                entries = []

            for entry in entries:
                if not entry:
                    continue
                row = {}
                for field in export_fields:
                    if field == "Title":
                        row[field] = entry.get('title', '')
                    elif field == "URL":
                        row[field] = entry.get('webpage_url', '')
                    elif field == "ID":
                        row[field] = entry.get('id', '')
                    # Add other fields as needed
                video_data.append(row)

            return jsonify({'videos': video_data})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # Use YouTube API
    if not api_key:
        return jsonify({'error': 'Missing YouTube API key'}), 400

    videos = []
    BATCH_SIZE = 10
    
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
    output_option = data.get('output_option', 'save')
    export_fields = data.get('export_fields', ["Title", "URL"])
    search_type = data.get('search_type', 'advanced')

    print(f"Download request: option={output_option}, dir={output_dir}")  # Debug log

    message, csv_path = get_videos_and_save(channel_url, output_dir, output_option, export_fields, search_type)
    print(f"get_videos_and_save returned: message={message}, path={csv_path}")  # Debug log

    if not message.startswith("Success"):
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
