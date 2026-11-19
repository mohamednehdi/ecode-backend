"""Stress test of the extraction web service (POST /api/v1/extract) with Locust.

    python stress/make_samples.py
    set API_KEY=ecode_...                      (PowerShell: $env:API_KEY = "ecode_...")
    locust -f stress/locustfile.py --headless -u 50 -r 10 -t 60s --host http://127.0.0.1:5000 --csv stress/results/run

Environment:
    API_KEY    key created in the back office (no quota, no IP restriction for the test)
    WORKLOAD   typical (default) | small | a4 | pdf | mix
               typical = 1200x900 PNG with 3 codes (reference workload of the 100 ms target)
"""
import os
import random

from locust import HttpUser, constant, task

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'samples')
FILES = {name: open(os.path.join(SAMPLES, name), 'rb').read() for name in os.listdir(SAMPLES)}
MIX = [('small.png', 5), ('typical.png', 4), ('a4.jpg', 1)]   # a realistic blend: mostly small images
API_KEY = os.environ['API_KEY']
WORKLOAD = os.environ.get('WORKLOAD', 'typical')
SINGLE = {'typical': 'typical.png', 'small': 'small.png', 'a4': 'a4.jpg', 'pdf': 'doc.pdf'}


class ApiClient(HttpUser):
    # Back-to-back requests: every user sends its next request as soon as it gets an answer
    wait_time = constant(0)

    @task
    def extract(self):
        if WORKLOAD == 'mix':
            name = random.choices([n for n, _ in MIX], weights=[w for _, w in MIX])[0]
        else:
            name = SINGLE[WORKLOAD]
        with self.client.post('/api/v1/extract', headers={'X-API-Key': API_KEY},
                              files={'file': (name, FILES[name])}, name=f'extract {name}',
                              catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f'HTTP {response.status_code}: {response.text[:100]}')
            elif not response.json().get('barcodes'):
                response.failure('no barcode found')   # a wrong answer counts as a failure too
