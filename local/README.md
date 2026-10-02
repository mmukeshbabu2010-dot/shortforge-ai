# ShortForge Local YouTube Bridge

The ShortForge web app normally sends a YouTube URL to the hosted API. YouTube can challenge hosted/datacenter IPs, so this optional local bridge moves only the YouTube download step onto your computer.

## Flow

ShortForge GitHub Pages -> Local Bridge -> YouTube

Then:

Local Bridge -> ShortForge Render API (uploaded video) -> analysis -> results

Your YouTube cookies, when supplied, are read and used locally. They are not forwarded to the Render API.

## Windows

1. Open this folder.
2. Double-click run.bat.
3. Keep the terminal window open.
4. Open ShortForge in your browser.
5. The YouTube panel should show Local bridge ready.
6. Paste a YouTube URL and click Analyze Video.

The bridge uses the same machine/network as your browser, which is important because video services can bind access to the same IP and session cookies.

## Cookies

Only use a cookies file for accounts/videos you are authorized to access. Keep the file private. ShortForge passes the selected cookies only to the local bridge; the bridge deletes its temporary cookie file after the download attempt.

## Configuration

Set SHORTFORGE_API_URL before starting the bridge if you host the API somewhere else.

Example:

set SHORTFORGE_API_URL=https://your-api.example.com
python agent.py

The default API is the ShortForge Render service.

## Notes

- This does not make YouTube downloads guaranteed; YouTube may still require additional anti-bot mechanisms.
- If the local bridge is not running, the web app keeps the existing hosted-download fallback.
- Uploaded videos continue to use the hosted /api/analyze upload path.
