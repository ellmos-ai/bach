#!/bin/bash
# MCP Server Cross-Platform Check
# Run on Mac/Linux to verify ellmos MCP servers work

echo "=== MCP Server Cross-Platform Check ==="
echo "Platform: $(uname -s) $(uname -m)"
echo "Node: $(node --version 2>/dev/null || echo 'NOT FOUND')"
echo ""

# Check installations
echo "--- Installed MCP Servers ---"
npm list -g --depth=0 2>/dev/null | grep -i ellmos || echo "(none found globally)"
echo ""

# Test FileCommander initialization
echo "--- FileCommander MCP Test ---"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
RESULT=$(echo "$INIT" | timeout 10 ellmos-filecommander-mcp 2>/dev/null | head -1)
if [ -n "$RESULT" ]; then
    echo "FileCommander: RESPONDED"
    echo "$RESULT" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.readline())
    info = d.get('result', {}).get('serverInfo', {})
    print(f\"  Name: {info.get('name', '?')}\")
    print(f\"  Version: {info.get('version', '?')}\")
except Exception as e:
    print(f'  Parse error: {e}')
" 2>/dev/null
else
    echo "FileCommander: NO RESPONSE"
fi
echo ""

# Test CodeCommander initialization
echo "--- CodeCommander MCP Test ---"
RESULT=$(echo "$INIT" | timeout 10 ellmos-codecommander-mcp 2>/dev/null | head -1)
if [ -n "$RESULT" ]; then
    echo "CodeCommander: RESPONDED"
    echo "$RESULT" | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.readline())
    info = d.get('result', {}).get('serverInfo', {})
    print(f\"  Name: {info.get('name', '?')}\")
    print(f\"  Version: {info.get('version', '?')}\")
except Exception as e:
    print(f'  Parse error: {e}')
" 2>/dev/null
else
    echo "CodeCommander: NO RESPONSE"
fi

echo ""
echo "=== DONE ==="
