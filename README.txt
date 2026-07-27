Gridiron IQ Mock Draft Lab

Upload/replace:
1. app.py
2. templates/mock_draft.html
3. templates/draft_center.html (included only to add the Mock Draft Lab button)

New page:
  /mock-draft

Features:
- Run 10, 25, 50, or 100 mock drafts at once
- Choose draft slot, rounds, and draft strategy
- Supports ESPN and Yahoo league profiles
- Simulates opponents around ADP with randomness
- Saves recent mock results in the Flask session
- Shows average roster grade
- Shows best roster grade
- Shows most common first-six-round draft sequences
- Shows best round-by-round roster from the last batch
- Lets you repeat batches to fine-tune your preferred draft sequence

Note:
The mock simulator currently uses the app's built-in player pool/ADP model. It is a strategy-training engine, not a live consensus-ADP feed yet.
