import ast
import sys

def test_syntax():
    with open('system/hub/_services/weather/weather_service.py') as f:
        source = f.read()
    try:
        ast.parse(source)
        print('Syntax OK')
        return True
    except SyntaxError as e:
        print(f'SyntaxError at line {e.lineno}: {e.msg}')
        print(f'Line text: {e.text}')
        return False

if __name__ == '__main__':
    sys.exit(0 if test_syntax() else 1)