# Gridiron IQ — Sync League Navigation Cleanup

Gridiron IQ now uses one visible league-management workflow: **Sync League**.

## Changes

- `/league-sync` remains the main ESPN and Yahoo connection/synchronization page.
- The duplicate `/connect-league` page registration was removed.
- Old `/connect-league` bookmarks receive a permanent redirect to `/league-sync`.
- Legacy `Connect League` navigation links from an older `base.html` are hidden
  automatically, so replacing the shared base template is not required.
- The dashboard now shows one Sync League button rather than separate Connect
  and Sync buttons.
- Disconnected dashboard messages consistently say Sync League.
- Daily AI priorities now direct users to Sync League.

This change does not remove ESPN or Yahoo authorization. It only removes the
duplicate label and page entry.
