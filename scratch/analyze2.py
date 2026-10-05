import json

with open('benchmarks/qwen-results-fixed.json') as f:
    data = json.load(f)

for case in data.get('cases', []):
    print(f"Case: {case['case_id']}, Expected: {case['expected']}")

print("\n---")
for row in data['rows']:
    if row['variant'] == 'adaptive' and row['case'] == 'Calculate 12 + 7':
        print(row)
