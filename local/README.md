# ShortForge Local AI Bridge

The local bridge is the recommended free way to use ShortForge analysis.

It keeps the heavy AI work on your own Windows PC:

- YouTube videos are downloaded on your PC.
- Uploaded videos are analyzed on your PC.
- Whisper transcription runs locally.
- YouTube cookies, if used, stay on your PC.
- Only the video plus the local transcription results are sent to the ShortForge API.
- Render is used for lightweight storage, thumbnails, and Short generation instead of running Whisper on the free server.

## Easiest Windows setup

1. Open ShortForge.
2. Click Download bridge in the Local AI bridge card.
3. Extract the ZIP.
4. Open the local folder.
5. Double-click run.bat.
6. Keep that window open.
7. Return to ShortForge and wait for Local bridge ready.
8. Upload a video or paste a YouTube URL and click Analyze Video.

The first analysis downloads the Whisper model to your PC. Later analyses reuse it.

## YouTube cookies

Cookies are optional. Use a fresh Netscape-format youtube.com cookies file only if YouTube still blocks the local download.

Cookies stay on the local bridge and are never uploaded to the Render API.

Never share a cookies file with anyone.

## What runs where

Your PC:
- YouTube download
- Whisper transcription
- local video analysis

ShortForge API:
- stores the temporary source video
- creates hook thumbnails
- prepares generated Shorts

This architecture avoids depending on the limited memory and CPU of a free server for Whisper.
