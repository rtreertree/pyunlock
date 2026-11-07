# Synthetic PDF fixtures

`factory.py` creates every document in a temporary test directory. No personal
documents, downloaded PDFs, or external services are used. The representative
fixture has two pages, text, an RGB image, Unicode metadata, a bookmark, an internal
link, a text annotation, a text form value, and an attachment. Encrypted variants
are generated for the dependency's RC4 and AES algorithms and user/owner passwords.

`content_snapshot` compares document structures and decoded image/attachment
content so round-trip tests detect more than a matching page count.
