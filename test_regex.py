#!/usr/bin/env python3
import re

pattern = r'^[0-9a-zA-Z_]+$'
test = 'bach-ci'
result = re.fullmatch(pattern, test)
print(f'Pattern: {pattern}')
print(f'Test string: {test}')
print(f'Full match: {result is not None}')
print(f'Partial match (search): {re.search(pattern, test) is not None}')

# Test what partial matches
if re.search(pattern, test):
    match = re.search(pattern, test)
    print(f'Partial matched: "{match.group()}"')