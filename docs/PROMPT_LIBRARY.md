# Local Prompt Library

Approve the current Final prompt, then choose **Save approved prompt**. Approval alone does not save anything. Editing the prompt revokes approval. Exact duplicate text with identical metadata is saved only once.

Open **Prompt Library** from the sidebar to search text/model/workflow/date, filter workflow and type, and browse ten prompts per page. The prompt box provides Streamlit's copy icon. Reuse loads the complete text into Final prompt and selects the saved workflow when available. Check settings and reference images and approve again before rendering. No model or rendering job is started by reuse. Delete requires Confirm delete; Cancel keeps the entry.

Storage: `data/prompt_library.sqlite3`, relative to the ComfyMax installation, independent of the launching directory. Stores exact text, UTC save timestamp, source LM Studio model when known, selected workflow filename and H3 type. Uses Python's built-in SQLite, short-lived connections, parameterized statements, transactional writes and a ten-second busy timeout. No external service or new dependency. Data is excluded from Git. Stop ComfyMax before copying this database for backup; restore it to the same location. Do not delete data when updating the app. This is an installation-wide library shared by users of that local ComfyMax server.

Changed: App.py; modules/prompt_library.py; pages/Prompt_Library.py; .gitignore; tests/test_prompt_library.py; docs/PROMPT_LIBRARY.md. Scene Builder and FlashVSR source remain unchanged.

Tests: `python -m unittest discover -s tests -p test_prompt_library.py -v`. Storage tests cover approval, blank text, Unicode/multiline exact preservation, reopening, duplicates, filters, concurrent writes and deletion. Streamlit AppTest covers approval/save/edit invalidation, search, cancel/confirm deletion and reuse through multipage navigation. Clipboard interaction itself requires a browser and is provided by the standard Streamlit code widget.
