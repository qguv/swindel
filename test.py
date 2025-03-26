from pathlib import Path
import sys

from parse_log import parse_logfile

test_dir = Path('example_logs')
errors_dir = Path('example_logs') / 'errors'

all_tests = set(test_dir.rglob('*.buckshot'))
error_tests = set(errors_dir.rglob('*.buckshot'))

ok_tests = all_tests.difference(error_tests)

for f in ok_tests:
    print('-' * len(str(f)))
    print(f)
    print('-' * len(str(f)))
    print()
    gs = parse_logfile(f.open('r'))
    if gs is None:
        print(f"unexpected failure in {f.name}")
        sys.exit(1)
    print()

print('=' * 80)
print()

for f in error_tests:
    print('-' * len(str(f)))
    print(f)
    print('-' * len(str(f)))
    print()
    gs = parse_logfile(f.open('r'))
    if gs is None:
        print("failed as expected :)")
    else:
        print(f"expected {f.name} to fail, but it passed")
        sys.exit(1)
    print()

print('=' * 80)
print()
print("all tests passed!")
