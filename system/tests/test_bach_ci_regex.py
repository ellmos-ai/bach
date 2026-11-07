#!/usr/bin/env python3
import re


def test_bach_ci_regex():
    pattern = r'^[0-9a-zA-Z_]+$'
    test = 'bach-ci'
    result = re.fullmatch(pattern, test)
    print(f'Pattern: {pattern}')
    print(f'Test string: {test}')
    print(f'Full match: {result is not None}')
    print(f'Partial match (search): {re.search(pattern, test) is not None}')

    # The pattern ^[0-9a-zA-Z_]+$ means: from start (^) to end ($),
    # one or more alphanumeric/underscore characters.
    # 'bach-ci' contains a hyphen which is NOT in the character class,
    # so neither fullmatch nor search will match.

    # To match just 'bach' from the start, use pattern without $
    pattern_no_end = r'^[0-9a-zA-Z_]+'
    search_result = re.search(pattern_no_end, test)
    print(f'Pattern without $: {pattern_no_end}')
    print(f'Search match: {search_result is not None}')
    if search_result:
        print(f'Matched: "{search_result.group()}"')

    # Return assertion for test
    assert result is None, "Full match should fail for 'bach-ci'"
    # Search with ^ anchor but no $ will match 'bach'
    assert search_result is not None
    assert search_result.group() == 'bach'


if __name__ == '__main__':
    test_bach_ci_regex()
    print("All tests passed!")