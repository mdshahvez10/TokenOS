import json
import sys

def main():
    try:
        with open('benchmarks/qwen-results-fixed.json') as f:
            data = json.load(f)
        
        print("Failed Adaptive Cases:")
        for row in data['rows']:
            if not row['success'] and row['variant'] == 'adaptive':
                print(f"- Case: {row['case']} | Status: {row['status']} | Steps: {row['steps']}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    main()
