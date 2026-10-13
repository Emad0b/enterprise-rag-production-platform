def parse_pdf(raw):
    import pymupdf

    with pymupdf.open(stream=raw, filetype="pdf") as pdf:
        if pdf.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        if not 0 < len(pdf) <= 300:
            raise ValueError("PDF must contain 1â€“300 pages")
        pages = [page.get_text(sort=True) for page in pdf]
    if not any(page.strip() for page in pages):
        raise ValueError(
            "No extractable text. Scanned PDFs need OCR, which is not enabled."
        )
    return pages
