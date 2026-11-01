"""Extract text and images from PDF files using PyMuPDF.

Usage:
    python scripts/extract_pdf.py <input_dir> [--output-dir <output_dir>]

For each .pdf in <input_dir>, creates a subdirectory with:
  - full_text.txt  (page-delimited plain text)
  - images/        (all embedded images as PNG)

If --output-dir is not specified, output goes alongside the PDFs in <input_dir>.
"""
import argparse
import os

import pymupdf
from tqdm import tqdm


def extract_pdf(pdf_path: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    full_text = []
    img_count = 0

    for page_num in tqdm(range(len(doc)), desc="  Pages", unit="pg"):
        page = doc[page_num]

        text = page.get_text()
        if text.strip():
            full_text.append(f"\n--- Page {page_num + 1} ---\n")
            full_text.append(text)

        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            try:
                pix = pymupdf.Pixmap(doc, xref)
                if pix.n - pix.alpha > 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                img_path = os.path.join(images_dir, f"page{page_num+1}_img{img_idx+1}.png")
                pix.save(img_path)
                img_count += 1
            except Exception as e:
                print(f"\n  Warning: Could not extract image on page {page_num+1}: {e}")

    text_path = os.path.join(out_dir, "full_text.txt")
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("".join(full_text))

    doc.close()
    lines = sum(1 for _ in open(text_path))
    print(f"  Done: {lines} lines of text, {img_count} images extracted")


def main():
    parser = argparse.ArgumentParser(description="Extract text and images from PDF files")
    parser.add_argument("input_dir", help="Directory containing PDF files")
    parser.add_argument("--output-dir", help="Output directory (default: same as input_dir)")
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    pdf_files = sorted(f for f in os.listdir(input_dir) if f.lower().endswith(".pdf"))
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        return

    print(f"Found {len(pdf_files)} PDF(s) in {input_dir}")

    for pdf_idx, pdf_file in enumerate(pdf_files, 1):
        base_name = pdf_file.rsplit(".", 1)[0]
        out_dir = os.path.join(output_dir, base_name)
        print(f"\n[{pdf_idx}/{len(pdf_files)}] {pdf_file}")
        extract_pdf(os.path.join(input_dir, pdf_file), out_dir)

    print("\nAll done!")


if __name__ == "__main__":
    main()
