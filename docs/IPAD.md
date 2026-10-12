# iPad setup

Enable Developer Mode, connect USB, unlock and trust the Windows PC. Open Apple Devices. Using the same Python environment/user as the listener:

```powershell
python -m pymobiledevice3 lockdown wifi-connections on
python -m pymobiledevice3 lockdown remotepairing
python -m pymobiledevice3 mounter auto-mount
```

Separate developer pairing is essential. Pairing completion may raise RemotePairingCompletedError: reconnect and verify. Put the selected device UDID in local config only. Never print or publish pairing records. After setup, use the same LAN without USB. Unlock once after reboot. The client remounts missing developer support over the trusted Wi-Fi tunnel when available.

Subscribe to clip-to-ipad on your ntfy server. Keep compatibility Shortcut names **SetClipboard** and **SendToWindows**; notification titles say Adams’Drop. Changing a Shortcut name without changing encoded actions breaks fallback.

SetClipboard: Shortcut Input URL -> Get Contents of URL -> Copy to Clipboard. Used for large-image/manual fallback. The URL contains a single-use token, not a reusable API key.

SendToWindows: Get Clipboard -> POST raw text/image to your relay /send?source=ipad, with the private X-Api-Key header and appropriate Content-Type. Preserve existing working actions when upgrading. Keep credentials in local Shortcut configuration, never screenshots or Git. Grant local-network and paste permissions as needed.

## Add original video sharing to SendToWindows

Edit the existing shortcut; keep its name, URL and private API key.

1. In the shortcut's Details, enable **Show in Share Sheet**. Add **Media** and **Files** to its accepted input types, alongside the existing Text/Images types.
2. If the shortcut currently starts with Get Clipboard, add **If Shortcut Input has any value**. In that branch, **Set Variable** `SendItem` to **Shortcut Input**. In Otherwise, keep **Get Clipboard** and **Set Variable** `SendItem` to **Clipboard**. Put the existing upload action after End If. A shortcut already uploading Shortcut Input directly needs no input branch.
3. In **Get Contents of URL**, keep `/send?source=ipad`, Method **POST**, and the existing **X-Api-Key** header. Set **Request Body → File** and **File → SendItem** (or Shortcut Input for a share-sheet-only shortcut). Remove any fixed Content-Type header so the File action can choose it; the relay recognizes MOV/MP4 bytes even with a generic or old image Content-Type. Do not add Encode Media, Convert Image or Base64 actions to the video path.
4. Share **one video at a time**. In Photos, use **Share → Options → Current**, then choose **SendToWindows**. For an original video already in Files, share the file directly. Keep the shortcut running until the upload finishes.

Windows saves the exact uploaded video in **Downloads/AdamsDrop**, checks its length and SHA-256 against the relay, and automatically opens File Explorer in the containing folder with the received file selected when full-screen protection is off. This happens even if receive notifications are disabled. An enabled video notification can reveal the file again on click. Automatic folder opening is skipped if protection starts before the Shell action; it is not replayed later. Video transfers leave the clipboard alone. Filenames receive a unique suffix to avoid overwriting earlier transfers; an optional URL-encoded `X-Filename` header preserves the original name stem.

Received screenshots/images still go to the Windows clipboard. An original file is also saved in **Downloads/AdamsDrop** with a separate unique filename for each image. Its notification says **Click to show in folder** and opens File Explorer with that saved image selected only when clicked. Screenshots never open a folder automatically. Saved video/image files remain until you delete them; earlier screenshots are no longer overwritten by the next receive.

The video limit is **2 GiB** per raw File upload. Small multipart uploads remain compatible within the 25 MiB envelope limit; use File for larger videos. Files waiting on the relay expire after ten minutes and are removed after fetching. Saved Windows videos remain until you delete them. The PC app must be running and outside protected full-screen activity. If upload/download fails, or full-screen protection interrupts it, share again; consumed fetch links cannot be retried.

The relay and Windows app never transcode or recompress videos. The checksum verifies the bytes from the upload through the Windows download; it cannot establish what Photos exported before upload. For exact preservation of a specific existing file, share that original from Files. Apple documents [Media/Files input types](https://support.apple.com/guide/shortcuts/apd7644168e1/ios), the [File request body](https://support.apple.com/guide/shortcuts/request-your-first-api-apd58d46713f/ios), and [Current sharing format](https://support.apple.com/guide/ipad/share-photos-and-videos-ipad4f44c78f/ipados).

## Send PDFs, CSVs, JSON and other files

In Files or an app that exports a file, share **one file → SendToWindows**. Keep the existing **Files** Share Sheet input type, **POST**, private **X-Api-Key**, and **Request Body → File → Shortcut Input** (or your SendItem variable). The same `/send?source=ipad` URL now accepts generic files. PDF bytes and file Content-Types such as text/csv or application/json are recognized automatically. Files stream without conversion, up to **2 GiB**, and save in **Downloads/AdamsDrop** after a length/SHA-256 check. Click their receive notification to reveal the saved file in Explorer; generic files do not open folders automatically and do not alter the clipboard.

To preserve the original name and extension, on the **shared-file branch** add **Get Details of Files → Name** for the input, then **URL Encode** that name. Add an **X-Filename** header to the upload whose value is the encoded name. Keep this out of the no-input clipboard-text branch. This also identifies text files such as `.csv`, `.json` and `.txt` when Shortcuts supplies only text/plain or application/octet-stream. Without a supplied name, known Content-Types get the appropriate default extension; an unidentified binary file gets `.bin`.

For a dedicated generic-file branch you can also use `/send?source=ipad&kind=file`, with the same File body and filename header. This explicitly saves even empty files or unnamed plain-text files. Apply that URL only to the generic-file branch: keep the existing default URL for clipboard text, screenshots and automatic-video behavior. Regular unnamed text/plain requests remain clipboard text, even when their content looks like JSON.

Small multipart file uploads are supported within the 25 MiB request limit; raw File is the normal shortcut body for larger files. Shared original bytes, including CSV newlines and JSON encoding, are preserved. Filenames are sanitized and receive a unique suffix; saved files remain until deleted. Keep the PC app running outside protected full-screen activity, and share again after interruption. Physical iPad file export and filename actions still need owner verification.

No custom iPad app is installed. Native background iPad-copy monitoring failed testing and is not shipped.

## Receive Windows files in Files

Create one new shortcut named **SaveToFiles**. Keep SetClipboard and SendToWindows as they are.

1. Add **Get Contents of URL**. Set its URL to the **Shortcut Input** variable and method to **GET**. No API-key header is needed: the notification supplies a single-use download link.
2. Add **Save File**, taking **Contents of URL** from the previous action. Expand its options, turn **Ask Where to Save** off, and tap the blue destination folder (often **Shortcuts**) and choose **Browse → On My iPad → Downloads**. Create Downloads there if needed. Leave **Subpath** blank to preserve the filename. Leave **Overwrite If File Exists** off.
3. Add **Quick Look** directly after Save File, with **Saved File** as its input. Tap Quick Look's blue input → **Select Variable** → tap the **Saved File** output beneath the Save File action. This opens a preview of the saved PDF/image with a Share button.

Do not put **Stop and Output** before Quick Look: it ends the shortcut and prevents the preview from running. To save locally, select **On My iPad → Downloads** in the destination folder picker. Do not type Downloads into Subpath while the destination still says Shortcuts; that names a subfolder inside Shortcuts.

Check that **Save File** shows the local Downloads folder selected through **On My iPad**. To find received files, open Files → Browse → On My iPad → Downloads. Keep the destination fixed and Subpath blank so each transfer uses its supplied filename without asking where to save. The download action performs one request per run; it does not poll or loop.

To leave Shortcuts when you finish previewing, add **Go to Home Screen** immediately **after Quick Look**. Tap **Done** in Quick Look; execution continues to the Home Screen action. Do not place it before Quick Look. Alternatively, use **Open App** after Quick Look and choose the app you always want to return to. These are owner edits on the iPad; neither has been physically verified here. This flow cannot automatically discover whichever app was active before you tapped the ntfy notification. Apple's [x-callback-url mechanism](https://support.apple.com/guide/shortcuts/use-x-callback-url-apdcd7f20a6f/ios) can return to an explicitly supplied app URL, which requires knowing the destination in advance. It does not identify the previously active app. Leaving Shortcuts does not delete SaveToFiles or the received file.

On Windows, select a PDF, PNG or other file, then **right-click → Show more options → Send to → AdamsDrop - iPad**. Alternatively, use **AdamsDrop tray → Send Files to iPad…**. Select up to sixteen files; each gets its own iPad notification. Tap each ntfy notification within **ten minutes**, and let the shortcut finish before opening the next. On first use, allow the relay/local-network and destination-folder access prompts. Quick Look previews it after saving; use its Share button to open it in another app. The file also remains in the folder selected by Save File.

This transfers the original file rather than an image conversion or clipboard representation. Downloads use an attachment filename and binary Content-Type to avoid Shortcuts parsing JSON/text. The relay accepts up to 2 GiB per file, within the shared 4 GiB temporary storage limit; very large downloads remain subject to iPad Shortcuts memory/storage limits and need device testing. Keep the iPad able to reach the relay (normally the same home Wi-Fi). Windows full-screen protection also applies to manual file sends.

All file extensions are accepted, including videos (MP4/MOV and others), JSON, TXT, CSV, Office documents, audio, archives and unknown formats. The transfer preserves original bytes; text/newlines are not rewritten and videos are not transcoded. Saving a file and previewing it are separate: Quick Look and installed apps determine which formats/codecs can be previewed or played. An unsupported preview does not add support for that format; check the saved file in Downloads and use an appropriate app. ZIP folders before sending.

The iPad notification means **ready to download**, not saved. Tapping opens Shortcuts; this workflow requires that interaction. If download or saving fails, resend from Windows because the fetch link is consumed once download starts. Check Files before retrying after a save error to avoid duplicate copies. Filename handling, destination permissions and physical PDF/PNG saves are owner acceptance checks, not proven by server tests.
