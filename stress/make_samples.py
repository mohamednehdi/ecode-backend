"""Generates the test documents used by the stress test (stress/samples/).

    python stress/make_samples.py

  small.png   300x300 crop with one QR code          (a client that sends only the barcode area)
  typical.png 1200x900 image with QR + Code128 + DataMatrix   (reference workload of the 100 ms target)
  a4.jpg      A4 scan at 200 dpi (1654x2339), 3 codes          (full page scan)
  doc.pdf     1-page A4 PDF with 3 codes
"""
import io
import os

import barcode
import numpy as np
import pymupdf
import segno
from barcode.writer import ImageWriter
from PIL import Image
from pylibdmtx.pylibdmtx import encode

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')


def _qr(text, scale):
    b = io.BytesIO()
    segno.make(text, error='m', micro=False).save(b, kind='png', scale=scale)
    return Image.open(b).convert('RGB')


def _code128(text):
    b = io.BytesIO()
    barcode.get('code128', text, writer=ImageWriter()).write(b)
    return Image.open(b).convert('RGB')


def _datamatrix(text, factor=3):
    e = encode(text.encode())
    return Image.frombytes('RGB', (e.width, e.height), e.pixels).resize((e.width * factor, e.height * factor), Image.NEAREST)


def page(width, height):
    img = Image.new('RGB', (width, height), 'white')
    img.paste(_qr('HELLO-QR', 8), (50, 50))
    img.paste(_code128('ABC-123'), (width // 2, 60))
    img.paste(_datamatrix('HELLO-DM'), (100, height // 2))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    _qr('HELLO-QR', 6).resize((300, 300)).save(os.path.join(OUT, 'small.png'))
    page(1200, 900).save(os.path.join(OUT, 'typical.png'))
    a4 = page(1654, 2339)
    a4.save(os.path.join(OUT, 'a4.jpg'), quality=85)

    jpg = io.BytesIO()
    a4.save(jpg, 'JPEG', quality=85)   # a scanned page is embedded as a JPEG
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_image(p.rect, stream=jpg.getvalue())
    doc.save(os.path.join(OUT, 'doc.pdf'))

    for name in sorted(os.listdir(OUT)):
        print(f'{name:12s} {os.path.getsize(os.path.join(OUT, name)) / 1024:7.0f} KB')


if __name__ == '__main__':
    main()
