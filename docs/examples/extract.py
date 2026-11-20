"""Sends a file to the eCode API and prints the barcodes found.

    python extract.py document.pdf
    python extract.py photo.jpg --thorough

Settings (environment variables):
    ECODE_URL   address of the service                     (default http://localhost:5000)
    ECODE_KEY   your API key, the one that starts with ecode_   (required)

Needs the `requests` package:  pip install requests
"""
import os
import sys

import requests

URL = os.environ.get('ECODE_URL', 'http://localhost:5000').rstrip('/')
KEY = os.environ.get('ECODE_KEY')


def extract(path, thorough=False):
    """Returns the JSON answer of the service. Raises RuntimeError with the service's message on an error."""
    with open(path, 'rb') as f:
        response = requests.post(
            f'{URL}/api/v1/extract',
            headers={'X-API-Key': KEY},
            params={'thorough': 1} if thorough else None,
            files={'file': (os.path.basename(path), f)},
            timeout=60,
        )
    if response.status_code != 200:
        # Every error answer is {"error": "message"}; 429 means the quota of the key is used up
        raise RuntimeError(f'{response.status_code}: {response.json().get("error", response.text)}')
    return response.json()


if __name__ == '__main__':
    if not KEY or len(sys.argv) < 2:
        sys.exit('usage: ECODE_KEY=ecode_... python extract.py <file.pdf|.png|.jpg> [--thorough]')
    try:
        result = extract(sys.argv[1], thorough='--thorough' in sys.argv)
    except RuntimeError as error:
        sys.exit(f'Error {error}')

    print(f"{result['file_type']}, {result['page_count']} page(s), {len(result['barcodes'])} code(s)")
    for code in result['barcodes']:
        box = code['coordinates']
        print(f"  page {code['page']}  {code['type']:<10} {code['data']}   at ({box['x']}, {box['y']}) {box['w']}x{box['h']}")
    for region in result['unread_regions']:
        print(f"  page {region['page']}  region that looks like a code but could not be read (confidence {region['score']})")
