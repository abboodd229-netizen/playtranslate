# Game packs

Each file gives a game a head start: names (`glossary`) and translated lines
(`translations`, English -> Arabic). The app downloads `index.json` at start-up
and imports any pack whose `version` is newer than the one it already has, for
games the player has. Imported lines never replace the player's own corrections.

To update a pack: in the app, Translation tab -> «صدّر ذاكرة هذي اللعبة», review
the file, replace the pack here and raise its `version` in `index.json`.
