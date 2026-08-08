# Sidebar Sync-Only Fix

## Result

The **Connect League** or **Connect a League** sidebar entry is removed. The sidebar keeps one connection option:

- **League Sync** → `/league-sync`

## Why the previous cleanup missed it

The deployed sidebar used the same `/league-sync` URL for both **Connect League** and **League Sync**. A URL-based rule could not distinguish the two entries.

This version removes either legacy label by its visible text before the HTML is sent to the browser. It also includes a small browser-side fallback for older sidebar markup. The old `/connect-league` route remains a redirect so saved bookmarks do not break.

## Files changed

- `app.py` — removes the legacy **Connect League** navigation item by label.
- `templates/dashboard.html` — already uses **Sync League** consistently.

## Verified behavior

The cleanup was tested against the exact sidebar HTML currently rendered by the deployed app:

- **Connect League / Connect a League:** 0 links
- **League Sync:** 1 link
