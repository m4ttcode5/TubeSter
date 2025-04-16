# YouTube Channel Video List Downloader

## Overview
A web tool to extract all video titles and URLs from a YouTube channel and save them as a CSV file. Includes a web UI with advanced features for video metadata extraction.

## Features
- Extracts all video URLs and titles from a YouTube channel
- Advanced metadata extraction (titles, descriptions, views, likes, etc.)
- YouTube API integration for faster metadata fetching
- Saves results as a CSV file
- Modern web interface built with Flask
- Disclaimer included

## Installation

1. **Clone the repository**

```bash
git clone https://your-repo-url.git
cd your-repo-directory
```

2. **Set up environment variables**

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required environment variables:
- `YOUTUBE_API_KEY`: Your YouTube Data API key (optional, enhances metadata fetching)

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

4. **Ensure `yt-dlp` is installed**

The project uses the `yt-dlp` Python package which is included in requirements.txt.

## Local Development

Run the Flask web app:

```bash
python server.py
```

Open your browser and go to `http://localhost:5000`.

## Production Deployment on Render

### 1. Create a new Web Service

1. Log in to [Render Dashboard](https://dashboard.render.com)
2. Click "New +" and select "Web Service"
3. Connect your repository
4. Give your service a name
5. Keep the Root Directory as `/`
6. Select the Region closest to your users
7. Select "Python 3" as the Runtime

### 2. Configure Build and Start Commands

In your Render dashboard:

- Build Command: `pip install -r requirements.txt`
- Start Command: `waitress-serve --host 0.0.0.0 --port $PORT server:app`

### 3. Add Environment Variables

In your Render dashboard, add the following environment variables:
- `YOUTUBE_API_KEY`: Your YouTube Data API key (recommended for production)

### 4. Deploy

1. Click "Create Web Service"
2. Wait for the build and deployment to complete
3. Your app will be available at `https://your-app-name.onrender.com`

### Post-Deployment Steps

1. Test your deployed application by visiting the Render URL
2. Monitor the application logs in Render dashboard
3. Set up health checks and monitoring if needed

## Security Considerations

1. Never commit `.env` file to version control
2. Keep your YouTube API key secure and monitor usage
3. Consider implementing rate limiting for production
4. Monitor your API quotas regularly

## Disclaimer
This tool is not affiliated with YouTube or Google. It is the user's responsibility to ensure that they have the right to download content. Downloading copyrighted material without permission may violate YouTube's Terms of Service and applicable laws. This service is intended for personal and fair-use purposes only.
