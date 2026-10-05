import urllib.request, json, sys
try:
    req = urllib.request.Request('http://localhost:11434/api/tags')
    with urllib.request.urlopen(req, timeout=5) as r:
        data = json.load(r)
    print('OK', len(data.get('models',[])), 'models')
    for m in data.get('models',[])[:5]:
        print(m.get('name'))
except Exception as e:
    print('ERR', e)
