# ShortForge Local YouTube Bridge

The bridge is an optional Windows helper that makes YouTube URL analysis easier and more reliable. Your PC downloads the YouTube video using your own network connection, then uploads only the downloaded video to the ShortForge analysis API.

## Easiest setup on Windows

1. Open the ShortForge website.
2. Under the YouTube URL box, click **Download bridge** if the status says **Setup needed**.
3. Extract the downloaded ZIP.
4. Open the **local** folder.
5. Double-click **run.bat**.
6. Keep that window open. The first run can install Python and the bridge dependencies automatically.
7. Return to ShortForge. The status should change to **Local bridge ready** automatically.
8. Paste your YouTube URL and click **Analyze Video**.

After the first setup, future use is simply: **double-click run.bat → open ShortForge → Analyze Video**.

## Cookies are optional

Do not select a cookies file unless YouTube still blocks the local download. If you use one, select a fresh Netscape-format youtube.com cookies file in ShortForge only after the local bridge is ready. The cookies are sent to the local bridge, used for the download attempt, and deleted from its temporary storage afterward. They are not uploaded to the Render analysis API.

Never share a cookies file with anyone; it can contain active login/session credentials.

## If the bridge says Setup needed

Make sure the run.bat window is still open. ShortForge checks the local helper automatically every few seconds. You do not need to refresh the page just because the bridge starts.

## Configuration

To use a different ShortForge API, set SHORTFORGE_API_URL before starting run.bat. The default is the hosted ShortForge API.

## Important

The bridge does not bypass YouTube rules or guarantee every video will download. Some videos may still require a fresh session/cookies or may not be available for download. Use videos you have permission to download.
