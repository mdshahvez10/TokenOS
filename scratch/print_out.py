import json
import time
import os

while not os.path.exists('benchmarks/out_calc_2.json'):
    time.sleep(1)

with open('benchmarks/out_calc_2.json') as f:
    data = json.load(f)

for row in data['rows']:
    print(f"Variant: {row['variant']}, Success: {row['success']}, Status: {row['status']}")
    # print the observations and errors if any
    
    # Unfortunately, out_calc_2.json only has rows, not the raw records!
