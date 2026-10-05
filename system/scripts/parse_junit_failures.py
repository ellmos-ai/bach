import xml.etree.ElementTree as ET
import sys
path = sys.argv[1] if len(sys.argv) > 1 else 'tests/.pytest_results.xml'
root = ET.parse(path).getroot()
found = False
for tc in root.iter('testcase'):
    failure = tc.find('failure')
    if failure is not None:
        found = True
        print('CLASS:', tc.get('classname'))
        print('NAME:', tc.get('name'))
        print('TIME:', tc.get('time'))
        print('MESSAGE:', failure.get('message'))
        print('TEXT:', failure.text)
        print('-' * 60)
if not found:
    print('No failures found.')
